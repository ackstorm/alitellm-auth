# SPDX-License-Identifier: Apache-2.0
import json

from app.oauth_as.grants import Grants


class FakeRedis:
    def __init__(self, data):
        self.data = data

    async def get(self, key):
        return self.data.get(key)


SERVICES = {"mcp-aws-eks-ro": {"store": "aws-eks-ro", "broker": "https://b"}}


async def test_granted_reads_the_pods_projection():
    g = Grants(
        FakeRedis({"oauth:aws-eks-ro:state:u@x.com": json.dumps({"granted": True, "updated": 1})}),
        SERVICES,
    )
    assert await g.granted("u@x.com", "mcp-aws-eks-ro") is True
    assert await g.granted("u@x.com", "mcp-google-drive") is False  # unknown service
    assert await g.granted("v@x.com", "mcp-aws-eks-ro") is False  # no record


async def test_a_stripped_grant_is_not_granted():
    g = Grants(
        FakeRedis({"oauth:aws-eks-ro:state:u@x.com": json.dumps({"granted": False})}), SERVICES
    )
    assert await g.granted("u@x.com", "mcp-aws-eks-ro") is False


async def test_scopes_for_keeps_the_audience_and_only_granted_services():
    g = Grants(
        FakeRedis({"oauth:aws-eks-ro:state:u@x.com": json.dumps({"granted": True})}),
        {**SERVICES, "mcp-google-drive": {"store": "google-drive", "broker": "https://c"}},
    )
    assert await g.scopes_for(
        "u@x.com", ["alitellm", "mcp-aws-eks-ro", "mcp-google-drive"], "alitellm"
    ) == ["alitellm", "mcp-aws-eks-ro"]
