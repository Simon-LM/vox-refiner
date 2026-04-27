'use client';

import { useEffect, useRef, useState } from 'react';
import styles from '@/styles/TtsDisplay.module.scss';

// ── Types ─────────────────────────────────────────────────────────────────────

interface DisplayChunk {
  char_start: number;
  char_end: number;
  topic: string;
  keywords: string[];
  summary_short: string;
}

interface AudioChunkInfo {
  text: string;
  char_start?: number;
  char_end?: number;
  duration_s?: number;
  receivedAt: number;  // performance.now() timestamp when the SSE event arrived
}

type DisplayMode = 'fulltext' | 'summary' | 'keywords';

interface TtsState {
  mode: string | null;
  displayMode: DisplayMode;
  total: number;
  chunks: Record<number, AudioChunkInfo>;
  fullChunks: string[];
  current: number;
  done: boolean;
  errorMsg: string | null;
  displayChunks: DisplayChunk[];
  totalChars: number;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function readDisplayMode(): DisplayMode {
  if (typeof window === 'undefined') return 'summary';
  const p = new URLSearchParams(window.location.search).get('displayMode');
  if (p === 'fulltext' || p === 'keywords') return p;
  return 'summary';
}

function findDisplayChunk(chunks: DisplayChunk[], charPos: number): DisplayChunk | null {
  if (!chunks.length) return null;
  // Linear scan is fine — display chunks are typically <30.
  for (const c of chunks) {
    if (charPos >= c.char_start && charPos < c.char_end) return c;
  }
  // Past the last chunk? Return it.
  if (charPos >= chunks[chunks.length - 1].char_start) return chunks[chunks.length - 1];
  return chunks[0];
}

function estimateCharPos(audio: AudioChunkInfo | undefined, now: number): number {
  if (!audio || audio.char_start === undefined || audio.char_end === undefined) return 0;
  const elapsed = (now - audio.receivedAt) / 1000;
  const duration = audio.duration_s && audio.duration_s > 0 ? audio.duration_s : 1;
  const fraction = Math.min(Math.max(elapsed / duration, 0), 1);
  return audio.char_start + fraction * (audio.char_end - audio.char_start);
}

// ── Mock state (dev preview — append ?mock to URL) ────────────────────────────

const mockSourceText =
  'Le renard brun et rapide saute par-dessus le chien paresseux.\n\n' +
  'La migration des oiseaux suit des routes ancestrales tracées depuis des millénaires.\n\n' +
  'VoxRefiner transforme votre texte sélectionné en audio de haute qualité.\n\n' +
  'Les modèles de langage permettent une synthèse vocale naturelle et expressive.\n\n' +
  "Fin de la lecture — merci d'avoir utilisé VoxRefiner.";

const mockDisplayChunks: DisplayChunk[] = (() => {
  const anchors = [
    { anchor: 'Le renard brun', topic: 'Renard et chien',           keywords: ['renard', 'saut', 'chien'],          summary_short: 'Un renard brun saute au-dessus du chien.' },
    { anchor: 'La migration',   topic: 'Migration des oiseaux',     keywords: ['migration', 'oiseaux', 'routes'],   summary_short: 'Les oiseaux migrent sur des routes ancestrales.' },
    { anchor: 'VoxRefiner',     topic: 'Transformation texte→audio', keywords: ['VoxRefiner', 'texte', 'audio'],     summary_short: 'VoxRefiner transforme le texte en audio.' },
    { anchor: 'Les modèles',    topic: 'Synthèse vocale naturelle', keywords: ['modèles', 'synthèse', 'naturelle'], summary_short: 'Les modèles produisent une synthèse naturelle.' },
    { anchor: 'Fin de la',      topic: 'Fin de lecture',            keywords: ['fin', 'lecture'],                   summary_short: 'La lecture se termine.' },
  ];
  let pos = 0;
  return anchors.map((a, i) => {
    const start = mockSourceText.indexOf(a.anchor, pos);
    pos = start + a.anchor.length;
    const end = i < anchors.length - 1 ? mockSourceText.indexOf(anchors[i + 1].anchor, pos) : mockSourceText.length;
    return { char_start: start, char_end: end, topic: a.topic, keywords: a.keywords, summary_short: a.summary_short };
  });
})();

const initialState: TtsState = {
  mode: null,
  displayMode: 'summary',
  total: 0,
  chunks: {},
  fullChunks: [],
  current: -1,
  done: false,
  errorMsg: null,
  displayChunks: [],
  totalChars: 0,
};

// ── Component ─────────────────────────────────────────────────────────────────

export default function TtsDisplay() {
  const [state, setState] = useState<TtsState>(initialState);
  // Tick state — increments via requestAnimationFrame to drive time-based
  // display chunk progression while an audio chunk is playing.
  const [tick, setTick] = useState(0);
  const rafRef = useRef<number | null>(null);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const displayMode = readDisplayMode();

    if (params.has('mock')) {
      const now = performance.now();
      setState({
        mode: 'voice',
        displayMode,
        total: 5,
        chunks: {
          0: { text: 'Le renard brun et rapide saute par-dessus le chien paresseux.',                  char_start: 0,   char_end: 60,  duration_s: 3, receivedAt: now },
          1: { text: 'La migration des oiseaux suit des routes ancestrales tracées depuis des millénaires.', char_start: 62,  char_end: 147, duration_s: 4, receivedAt: now },
          2: { text: 'VoxRefiner transforme votre texte sélectionné en audio de haute qualité.',       char_start: 149, char_end: 219, duration_s: 4, receivedAt: now },
          3: { text: 'Les modèles de langage permettent une synthèse vocale naturelle et expressive.', char_start: 221, char_end: 297, duration_s: 4, receivedAt: now },
          4: { text: "Fin de la lecture — merci d'avoir utilisé VoxRefiner.",                          char_start: 299, char_end: 350, duration_s: 3, receivedAt: now },
        },
        fullChunks: [],
        current: 2,
        done: false,
        errorMsg: null,
        displayChunks: mockDisplayChunks,
        totalChars: mockSourceText.length,
      });
      return;
    }

    setState(prev => ({ ...prev, displayMode }));

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
          next.displayChunks = [];
          next.totalChars = 0;
          const fullText = payload?.full_text as string | undefined;
          next.fullChunks = fullText
            ? fullText.split(/\n\s*\n+/).map(s => s.trim()).filter(Boolean)
            : [];
        } else if (type === 'chunk') {
          const idx = typeof payload?.idx === 'number' ? payload.idx : -1;
          if (idx >= 0) {
            const audio: AudioChunkInfo = {
              text: (payload?.text as string) || '',
              char_start: typeof payload?.char_start === 'number' ? payload.char_start : undefined,
              char_end:   typeof payload?.char_end   === 'number' ? payload.char_end   : undefined,
              duration_s: typeof payload?.duration_s === 'number' ? payload.duration_s : undefined,
              receivedAt: performance.now(),
            };
            next.chunks = { ...prev.chunks, [idx]: audio };
            next.current = idx;
          }
        } else if (type === 'display_chunks') {
          const chunks = (payload?.chunks as DisplayChunk[] | undefined) || [];
          next.displayChunks = chunks;
          next.totalChars = (payload?.total_chars as number) || 0;
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

    es.addEventListener('init',           e => apply('init',           parse(e)));
    es.addEventListener('chunk',          e => apply('chunk',          parse(e)));
    es.addEventListener('display_chunks', e => apply('display_chunks', parse(e)));
    es.addEventListener('done',           () => apply('done',          null));
    es.addEventListener('error',          e => apply('error',          parse(e)));

    return () => es.close();
  }, []);

  // ── rAF loop: drives time-based display chunk progression within an audio chunk
  useEffect(() => {
    if (state.done || state.current < 0 || state.displayChunks.length === 0) {
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
      return;
    }
    const loop = () => {
      setTick(t => (t + 1) % 1000000);
      rafRef.current = requestAnimationFrame(loop);
    };
    rafRef.current = requestAnimationFrame(loop);
    return () => {
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
    };
  }, [state.current, state.done, state.displayChunks.length]);

  // ── Derived state ───────────────────────────────────────────────────────────

  const isPreInit = state.current < 0;
  const isInsight = state.mode === 'insight';
  const source = isInsight ? state.fullChunks : null;

  const currentAudio = state.chunks[state.current];
  const currentText = currentAudio?.text || state.fullChunks[state.current] || '';
  const beforeText = !isPreInit
    ? (source ? source[state.current - 1] : state.chunks[state.current - 1]?.text) ?? ''
    : '';
  const afterText = !isPreInit
    ? (source ? source[state.current + 1] : state.chunks[state.current + 1]?.text) ?? ''
    : '';

  const preInitCurrent = isPreInit && isInsight && state.fullChunks.length > 0
    ? state.fullChunks[0]
    : null;
  const preInitAfter = isPreInit && isInsight
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

  // ── Smart display: time-based char position → display chunk lookup ──────────
  // tick is read inside estimateCharPos via performance.now() — referencing it
  // here ensures React re-renders this branch on each rAF tick.
  void tick;
  const charPos = estimateCharPos(currentAudio, performance.now());
  const displayChunk = isPreInit ? null : findDisplayChunk(state.displayChunks, charPos);

  const renderContent = (): string => {
    if (isPreInit) return preInitCurrent ?? 'En attente de la lecture…';
    if (displayChunk) {
      if (state.displayMode === 'keywords') return displayChunk.keywords.join(' · ');
      if (state.displayMode === 'summary')  return displayChunk.summary_short;
    }
    return currentText;
  };

  const showTopic = !isPreInit && state.displayMode !== 'fulltext' && !!displayChunk?.topic;
  const isKeywordsMode = state.displayMode === 'keywords';

  return (
    <div className={styles.app}>
      <div className={styles.status}>
        <span className={styles.modeBadge}>{state.mode ?? '…'}</span>
        {state.displayMode !== 'fulltext' && (
          <span className={styles.displayModeBadge}>{state.displayMode}</span>
        )}
        <span>{progress}</span>
      </div>

      <div className={styles.stage}>
        <div className={`${styles.ctx} ${styles.before}`}>
          {isPreInit ? '' : beforeText}
        </div>

        {showTopic && (
          <div className={styles.topic}>{displayChunk!.topic}</div>
        )}

        <div className={[
          styles.current,
          isPreInit ? styles.preInit : '',
          isKeywordsMode ? styles.keywords : '',
        ].filter(Boolean).join(' ')}>
          {renderContent()}
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
