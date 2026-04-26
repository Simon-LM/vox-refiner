'use client';

import { useEffect, useState } from 'react';
import styles from '@/styles/TtsDisplay.module.scss';

interface TtsState {
  mode: string | null;
  total: number;
  chunks: Record<number, string>;
  fullChunks: string[];
  current: number;
  done: boolean;
  errorMsg: string | null;
}

const initialState: TtsState = {
  mode: null,
  total: 0,
  chunks: {},
  fullChunks: [],
  current: -1,
  done: false,
  errorMsg: null,
};

export default function TtsDisplay() {
  const [state, setState] = useState<TtsState>(initialState);

  useEffect(() => {
    const es = new EventSource('/events');

    const apply = (type: string, payload: Record<string, unknown> | null) => {
      setState(prev => {
        const next = { ...prev };
        if (type === 'init') {
          next.mode = (payload?.mode as string) || 'voice';
          next.total = (payload?.total as number) || 0;
          next.chunks = {};
          next.current = -1;
          next.done = false;
          next.errorMsg = null;
          const fullText = payload?.full_text as string | undefined;
          next.fullChunks = fullText
            ? fullText.split(/\n\s*\n+/).map(s => s.trim()).filter(Boolean)
            : [];
        } else if (type === 'chunk') {
          const idx = typeof payload?.idx === 'number' ? payload.idx : -1;
          if (idx >= 0) {
            next.chunks = { ...prev.chunks, [idx]: (payload?.text as string) || '' };
            next.current = idx;
          }
        } else if (type === 'done') {
          next.done = true;
        } else if (type === 'error') {
          next.errorMsg = (payload?.message as string) || 'erreur';
        }
        return next;
      });
    };

    const parse = (e: Event) => {
      try { return JSON.parse((e as MessageEvent).data); } catch { return null; }
    };

    es.addEventListener('init',  e => apply('init',  parse(e)));
    es.addEventListener('chunk', e => apply('chunk', parse(e)));
    es.addEventListener('done',  () => apply('done', null));
    es.addEventListener('error', e => apply('error', parse(e)));

    return () => es.close();
  }, []);

  const isPreInit = state.current < 0;
  const source = state.mode === 'insight' ? state.fullChunks : null;

  const currentText = state.chunks[state.current] || state.fullChunks[state.current] || '';
  const beforeText = !isPreInit
    ? (source ? source[state.current - 1] : state.chunks[state.current - 1]) ?? ''
    : '';
  const afterText = !isPreInit && source
    ? source[state.current + 1] ?? ''
    : '';

  const preInitCurrent = isPreInit && state.mode === 'insight' && state.fullChunks.length > 0
    ? state.fullChunks[0]
    : null;
  const preInitAfter = isPreInit && state.mode === 'insight'
    ? state.fullChunks.slice(1, 3).join(' · ')
    : '';

  const total = state.total || state.fullChunks.length || (state.current + 1);
  const progress = isPreInit
    ? (state.total > 0 ? `0 / ${state.total} passages` : 'en attente…')
    : `${state.current + 1} / ${total} passages`;

  const footerText = state.errorMsg
    ? `⚠ ${state.errorMsg}`
    : state.done
      ? '✓ Lecture terminée'
      : 'VoxRefiner';

  return (
    <div className={styles.app}>
      <div className={styles.status}>
        <span className={styles.modeBadge}>{state.mode ?? '…'}</span>
        <span>{progress}</span>
      </div>

      <div className={styles.stage}>
        <div className={`${styles.ctx} ${styles.before}`}>
          {isPreInit ? '' : beforeText}
        </div>

        <div className={`${styles.current}${isPreInit ? ` ${styles.preInit}` : ''}`}>
          {isPreInit ? (preInitCurrent ?? 'En attente de la lecture…') : currentText}
        </div>

        <div className={`${styles.ctx} ${styles.after}`}>
          {isPreInit ? preInitAfter : afterText}
        </div>
      </div>

      <div className={`${styles.footer}${state.done ? ` ${styles.done}` : ''}`}>
        {footerText}
      </div>
    </div>
  );
}
