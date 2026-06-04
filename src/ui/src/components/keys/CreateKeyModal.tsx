// CreateKeyModal.tsx — the single create-key modal (DASH-04), ported from
// src/ui/create-key.js (Preact -> React + shadcn Dialog). Driven by the
// create-key-modal open-state store (no prop-drilling): the keys table CTA and
// the sidebar shortcut both call openModal().
//
// Two views toggled by local `result` state:
//   FORM   — two OPTIONAL fields (name -> alias, expires -> duration) with
//            client validation mirrored from session.py (validateAlias /
//            validateDuration), submitting via useCreateKey.
//   RESULT — after a 200, the full sk- is shown ONCE with the locked
//            shown-once warning + a copy button, then a `done` button closes.
//
// SECURITY (threat T-10-09, Information Disclosure):
//   - The full `sk-` lives ONLY in local `result` state + the in-memory
//     fresh-keys store (written by useCreateKey.onSuccess, NOT here).
//   - It is NEVER written to any web Storage, NEVER logged (no console.*),
//     NEVER placed in a title / aria-label / thrown error. It renders only as
//     element text in the result view (React escapes it — no innerHTML sink).
//   - useCreateKey.onSuccess ALREADY stashes the fresh sk- and invalidates the
//     keys query; this modal only DISPLAYS the returned key once.

import { useCallback, useState } from 'react';

import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { useCopyFeedback } from '@/hooks/use-copy-feedback';
import { useCreateKey } from '@/hooks/use-keys';
import type { CreateKeyBody } from '@/lib/api-types';
import {
  CREATE_502_ERROR,
  SHOWN_ONCE_WARNING,
  validateAlias,
  validateDuration,
} from '@/lib/key-validation';
import { useCreateKeyModalStore } from '@/stores/create-key-modal';

/** The shown-once create response held in local state (id + full sk- `key`). */
interface CreateResult {
  id: string;
  key: string;
}

export function CreateKeyModal() {
  const open = useCreateKeyModalStore((s) => s.open);
  const closeModal = useCreateKeyModalStore((s) => s.closeModal);

  const [alias, setAlias] = useState('');
  const [duration, setDuration] = useState('');
  const [aliasError, setAliasError] = useState<string | null>(null);
  const [durationError, setDurationError] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  // `result` switches the modal from the form view to the shown-once key view
  // after a 200. Kept in component state only — never persisted (T-10-09).
  const [result, setResult] = useState<CreateResult | null>(null);

  const createKey = useCreateKey();
  const submitting = createKey.isPending;
  const { copied, copy } = useCopyFeedback();

  // Reset every transient field then bubble the close up via the store. Wired to
  // Cancel / done AND to onOpenChange(false) (Esc / overlay click).
  const handleClose = useCallback(() => {
    setAlias('');
    setDuration('');
    setAliasError(null);
    setDurationError(null);
    setFormError(null);
    setResult(null);
    closeModal();
  }, [closeModal]);

  const onSubmit = useCallback(
    async (e: React.FormEvent<HTMLFormElement>) => {
      e.preventDefault();
      if (submitting) return;
      setFormError(null);

      const aliasValue = alias.trim();
      const durationValue = duration.trim();

      // Mirror session.py validation BEFORE the request so the locked field
      // messages surface without a round-trip.
      const aErr = validateAlias(aliasValue);
      const dErr = validateDuration(durationValue);
      setAliasError(aErr);
      setDurationError(dErr);
      if (aErr || dErr) return;

      // Body omits empty fields — an empty body is valid (session.py defaults).
      const body: CreateKeyBody = {};
      if (aliasValue) body.alias = aliasValue;
      if (durationValue) body.duration = durationValue;

      try {
        const data = await createKey.mutateAsync(body);
        // Show the full sk- ONCE; the fresh-key stash + list invalidation are
        // ALREADY handled by useCreateKey.onSuccess — do NOT duplicate here.
        setResult({ id: data.id, key: data.key });
      } catch (e) {
        const err = e as { status?: number; detail?: string | null };
        if (err.status === 422 && err.detail) {
          // The backend returns ONE field rejection at a time with a specific
          // `detail`. Route it to the matching field; otherwise a form-level
          // error. Do NOT recompute the other field's validation here (WR-03).
          const detail = err.detail;
          if (detail.includes('alias')) setAliasError(detail);
          else if (detail.includes('duration')) setDurationError(detail);
          else setFormError(detail);
          return;
        }
        // 502 (or any other non-200 without a routable detail): in-form error.
        setFormError(CREATE_502_ERROR);
      }
    },
    [alias, duration, submitting, createKey],
  );

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (!o) handleClose();
      }}
    >
      <DialogContent className="max-w-md">
        {result ? (
          // ── Shown-once result view ──────────────────────────────────────
          <>
            <DialogHeader>
              <DialogTitle>Key created</DialogTitle>
              <DialogDescription className="leading-relaxed text-primary">
                {SHOWN_ONCE_WARNING}
              </DialogDescription>
            </DialogHeader>
            <div className="flex flex-col gap-4">
              <div className="break-all rounded-md border border-border bg-background px-3 py-3 font-mono text-sm text-primary">
                {result.key}
              </div>
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="self-start"
                onClick={() => void copy(result.key)}
              >
                {copied ? 'copied!' : 'copy'}
              </Button>
            </div>
            <div className="flex justify-end">
              <Button type="button" onClick={handleClose}>
                done
              </Button>
            </div>
          </>
        ) : (
          // ── Form view ───────────────────────────────────────────────────
          <form onSubmit={onSubmit} className="contents">
            <DialogHeader>
              <DialogTitle>Create Key</DialogTitle>
              <DialogDescription>
                Generate a new virtual key. Both fields are optional.
              </DialogDescription>
            </DialogHeader>
            <div className="flex flex-col gap-4">
              <div className="flex flex-col gap-1.5">
                <label
                  htmlFor="ck-name"
                  className="font-mono text-xs font-semibold uppercase tracking-wide text-text-secondary"
                >
                  name
                </label>
                <Input
                  id="ck-name"
                  type="text"
                  placeholder="key-YYYY-MM-DD"
                  value={alias}
                  onChange={(e) => setAlias(e.target.value)}
                  disabled={submitting}
                  aria-invalid={aliasError ? true : undefined}
                />
                <p className="text-xs text-text-secondary">
                  Letters, numbers, dash, underscore, dot. Up to 128 characters.
                </p>
                {aliasError ? (
                  <p className="text-xs text-destructive">{aliasError}</p>
                ) : null}
              </div>

              <div className="flex flex-col gap-1.5">
                <label
                  htmlFor="ck-expires"
                  className="font-mono text-xs font-semibold uppercase tracking-wide text-text-secondary"
                >
                  expires
                </label>
                <Input
                  id="ck-expires"
                  type="text"
                  placeholder="no expiry"
                  value={duration}
                  onChange={(e) => setDuration(e.target.value)}
                  disabled={submitting}
                  aria-invalid={durationError ? true : undefined}
                />
                <p className="text-xs text-text-secondary">
                  Leave blank for no expiry. Format: 90d, 24h, 30m.
                </p>
                {durationError ? (
                  <p className="text-xs text-destructive">{durationError}</p>
                ) : null}
              </div>

              {formError ? (
                <p className="text-xs text-destructive">{formError}</p>
              ) : null}
            </div>
            <div className="flex justify-end gap-3">
              <Button
                type="button"
                variant="outline"
                onClick={handleClose}
                disabled={submitting}
              >
                Cancel
              </Button>
              <Button type="submit" disabled={submitting}>
                Create Key
              </Button>
            </div>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}
