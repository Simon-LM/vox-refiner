/** @format */

"use client";

import { useEffect, useRef, useState } from "react";
import styles from "@/styles/TtsDisplay.module.scss";

// ── Types ─────────────────────────────────────────────────────────────────────

interface DisplayChunk {
	char_start: number;
	char_end: number;
	topic: string;
	keywords: string[];
	summary_short: string;
	quote_short: string;
}

interface AudioChunkInfo {
	text: string;
	char_start?: number;
	char_end?: number;
	duration_s?: number;
	receivedAt: number; // performance.now() timestamp when the SSE event arrived
}

type DisplayMode =
	| "summary"
	| "summary_keywords"
	| "keywords"
	| "keywords_quote"
	| "quote"
	| "fulltext";

const ALL_MODES: DisplayMode[] = [
	"summary",
	"summary_keywords",
	"keywords",
	"keywords_quote",
	"quote",
	"fulltext",
];
const MODE_LABEL: Record<DisplayMode, string> = {
	summary: "Résumé",
	summary_keywords: "dual",
	keywords: "Mots-clés",
	keywords_quote: "dual",
	quote: "Citations",
	fulltext: "Texte exact",
};

/** Modes principaux affichés dans la rangée (sans "Texte exact") */
const PRIMARY_MODES: DisplayMode[] = [
	"summary",
	"summary_keywords",
	"keywords",
	"keywords_quote",
	"quote",
];

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
	if (typeof window === "undefined") return "summary";
	const p = new URLSearchParams(window.location.search).get("displayMode");
	if (p && (ALL_MODES as string[]).includes(p)) return p as DisplayMode;
	return "summary";
}

function findDisplayChunk(
	chunks: DisplayChunk[],
	charPos: number,
): DisplayChunk | null {
	if (!chunks.length) return null;
	for (const c of chunks) {
		if (charPos >= c.char_start && charPos < c.char_end) return c;
	}
	if (charPos >= chunks[chunks.length - 1].char_start)
		return chunks[chunks.length - 1];
	return chunks[0];
}

function estimateCharPos(
	audio: AudioChunkInfo | undefined,
	now: number,
): number {
	if (!audio || audio.char_start === undefined || audio.char_end === undefined)
		return 0;
	const elapsed = (now - audio.receivedAt) / 1000;
	const duration =
		audio.duration_s && audio.duration_s > 0 ? audio.duration_s : 1;
	const fraction = Math.min(Math.max(elapsed / duration, 0), 1);
	return audio.char_start + fraction * (audio.char_end - audio.char_start);
}

// ── Mock state (dev preview — append ?mock to URL) ────────────────────────────

const mockSourceText =
	"• Le renard brun et rapide saute par-dessus le chien paresseux.\n\n" +
	"• La migration des oiseaux suit des routes ancestrales tracées depuis des millénaires.\n\n" +
	"• VoxRefiner transforme votre texte sélectionné en audio de haute qualité.\n\n" +
	"• Les modèles de langage permettent une synthèse vocale naturelle et expressive.\n\n" +
	"Fin de la lecture — merci d'avoir utilisé VoxRefiner.";

const mockDisplayChunks: DisplayChunk[] = (() => {
	const anchors = [
		{
			anchor: "Le renard brun",
			topic: "Renard et chien",
			keywords: ["renard", "saut", "chien"],
			summary_short: "Le renard brun saute par-dessus le chien paresseux.",
			quote_short: "Le renard brun saute par-dessus le chien",
		},
		{
			anchor: "La migration",
			topic: "Migration des oiseaux",
			keywords: ["migration", "oiseaux", "routes"],
			summary_short: "Les oiseaux suivent des routes ancestrales millénaires.",
			quote_short: "des routes ancestrales tracées depuis des millénaires",
		},
		{
			anchor: "VoxRefiner",
			topic: "Transformation texte→audio",
			keywords: [" 2 VoxRefiner", "texte", "audio"],
			summary_short:
				"1 VoxRefiner transforme le texte en audio de haute qualité.",
			quote_short: "3 transforme votre texte sélectionné en audio",
		},
		{
			anchor: "Les modèles",
			topic: "Synthèse vocale naturelle",
			keywords: ["modèles", "synthèse", "naturelle"],
			summary_short:
				"Les modèles permettent une synthèse vocale naturelle et expressive.",
			quote_short: "une synthèse vocale naturelle et expressive",
		},
		{
			anchor: "Fin de la",
			topic: "Fin de lecture",
			keywords: ["fin", "lecture", "VoxRefiner"],
			summary_short: "Fin de la lecture, merci d'avoir utilisé VoxRefiner.",
			quote_short: "Fin de la lecture — merci d'avoir utilisé VoxRefiner",
		},
	];
	let pos = 0;
	return anchors.map((a, i) => {
		const start = mockSourceText.indexOf(a.anchor, pos);
		pos = start + a.anchor.length;
		const end =
			i < anchors.length - 1
				? mockSourceText.indexOf(anchors[i + 1].anchor, pos)
				: mockSourceText.length;
		return {
			char_start: start,
			char_end: end,
			topic: a.topic,
			keywords: a.keywords,
			summary_short: a.summary_short,
			quote_short: a.quote_short,
		};
	});
})();

const initialState: TtsState = {
	mode: null,
	displayMode: "summary",
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
	const [tick, setTick] = useState(0);
	const rafRef = useRef<number | null>(null);
	const bubbleRef = useRef<HTMLDivElement>(null);
	const scrolledRef = useRef(false);

	// Keyboard shortcuts: 1–6 toggle the display mode.
	useEffect(() => {
		const onKey = (e: KeyboardEvent) => {
			if (
				e.target instanceof HTMLInputElement ||
				e.target instanceof HTMLTextAreaElement
			)
				return;
			const idx = ["1", "2", "3", "4", "5", "6"].indexOf(e.key);
			if (idx >= 0) {
				e.preventDefault();
				setState((prev) => ({ ...prev, displayMode: ALL_MODES[idx] }));
			}
		};
		window.addEventListener("keydown", onKey);
		return () => window.removeEventListener("keydown", onKey);
	}, []);

	useEffect(() => {
		const params = new URLSearchParams(window.location.search);
		const displayMode = readDisplayMode();

		if (params.has("mock")) {
			const now = performance.now();
			setState({
				mode: "voice",
				displayMode,
				total: 5,
				chunks: {
					0: {
						text: "Le renard brun et rapide saute par-dessus le chien paresseux.",
						char_start: 0,
						char_end: 60,
						duration_s: 3,
						receivedAt: now,
					},
					1: {
						text: "La migration des oiseaux suit des routes ancestrales tracées depuis des millénaires.",
						char_start: 62,
						char_end: 147,
						duration_s: 4,
						receivedAt: now,
					},
					2: {
						text: "• 5 VoxRefiner transforme votre texte sélectionné en audio de haute qualité.\n • VoxRefiner transforme votre texte sélectionné en audio de haute qualité.\n • VoxRefiner transforme votre texte sélectionné en audio de haute qualité.",
						char_start: 149,
						char_end: 219,
						duration_s: 4,
						receivedAt: now,
					},
					3: {
						text: "Les modèles de langage permettent une synthèse vocale naturelle et expressive.",
						char_start: 221,
						char_end: 297,
						duration_s: 4,
						receivedAt: now,
					},
					4: {
						text: "Fin de la lecture — merci d'avoir utilisé VoxRefiner.",
						char_start: 299,
						char_end: 350,
						duration_s: 3,
						receivedAt: now,
					},
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

		setState((prev) => ({ ...prev, displayMode }));

		const es = new EventSource("/events");

		const apply = (type: string, payload: Record<string, unknown> | null) => {
			setState((prev) => {
				const next = { ...prev };
				if (type === "init") {
					next.mode = (payload?.mode as string) || "voice";
					next.total = (payload?.total as number) || 0;
					next.chunks = {};
					next.current = -1;
					next.done = false;
					next.errorMsg = null;
					next.displayChunks = [];
					next.totalChars = 0;
					const fullText = payload?.full_text as string | undefined;
					next.fullChunks = fullText
						? fullText
								.split(/\n\s*\n+/)
								.map((s) => s.trim())
								.filter(Boolean)
						: [];
				} else if (type === "chunk") {
					const idx = typeof payload?.idx === "number" ? payload.idx : -1;
					if (idx >= 0) {
						const audio: AudioChunkInfo = {
							text: (payload?.text as string) || "",
							char_start:
								typeof payload?.char_start === "number"
									? payload.char_start
									: undefined,
							char_end:
								typeof payload?.char_end === "number"
									? payload.char_end
									: undefined,
							duration_s:
								typeof payload?.duration_s === "number"
									? payload.duration_s
									: undefined,
							receivedAt: performance.now(),
						};
						next.chunks = { ...prev.chunks, [idx]: audio };
						next.current = idx;
					}
				} else if (type === "display_chunks") {
					const chunks = (payload?.chunks as DisplayChunk[] | undefined) || [];
					next.displayChunks = chunks;
					next.totalChars = (payload?.total_chars as number) || 0;
				} else if (type === "done") {
					next.done = true;
				} else if (type === "error") {
					next.errorMsg = (payload?.message as string) || "erreur";
				}
				return next;
			});
		};

		const parse = (e: Event) => {
			try {
				return JSON.parse((e as MessageEvent).data);
			} catch {
				return null;
			}
		};

		es.addEventListener("init", (e) => apply("init", parse(e)));
		es.addEventListener("chunk", (e) => apply("chunk", parse(e)));
		es.addEventListener("display_chunks", (e) =>
			apply("display_chunks", parse(e)),
		);
		es.addEventListener("done", () => apply("done", null));
		es.addEventListener("error", (e) => apply("error", parse(e)));

		return () => es.close();
	}, []);

	// ── Center bubble on first chunk ─────────────────────────────────────────
	useEffect(() => {
		if (state.current >= 0 && !scrolledRef.current) {
			scrolledRef.current = true;
			bubbleRef.current?.scrollIntoView({ block: "center" });
		}
	}, [state.current]);

	// ── rAF loop: drives time-based display chunk progression ──────────────────
	useEffect(() => {
		if (state.done || state.current < 0 || state.displayChunks.length === 0) {
			if (rafRef.current !== null) {
				cancelAnimationFrame(rafRef.current);
				rafRef.current = null;
			}
			return;
		}
		const loop = () => {
			setTick((t) => (t + 1) % 1000000);
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
	const isInsight = state.mode === "insight";
	const source = isInsight ? state.fullChunks : null;

	const currentAudio = state.chunks[state.current];
	const currentText =
		currentAudio?.text || state.fullChunks[state.current] || "";
	const beforeText = !isPreInit
		? ((source
				? source[state.current - 1]
				: state.chunks[state.current - 1]?.text) ?? "")
		: "";
	const afterText = !isPreInit
		? ((source
				? source[state.current + 1]
				: state.chunks[state.current + 1]?.text) ?? "")
		: "";

	const preInitCurrent =
		isPreInit && isInsight && state.fullChunks.length > 0
			? state.fullChunks[0]
			: null;
	const preInitAfter =
		isPreInit && isInsight ? state.fullChunks.slice(1, 3).join(" · ") : "";

	const total = state.total || state.fullChunks.length || state.current + 1;
	const progress = isPreInit
		? state.total > 0
			? `0 / ${state.total} passages`
			: "en attente…"
		: `${state.current + 1} / ${total} passages`;

	const footerText = state.errorMsg
		? `⚠ ${state.errorMsg}`
		: state.done
			? "✓ Lecture terminée"
			: "";

	// ── Smart display lookup ────────────────────────────────────────────────────
	void tick;
	const charPos = estimateCharPos(currentAudio, performance.now());
	const displayChunk = isPreInit
		? null
		: findDisplayChunk(state.displayChunks, charPos);

	// ── Rendering helpers ─────────────────────────────────────────────────────

	/** Returns the primary displayed text for simple modes. */
	const renderMain = (): string => {
		if (isPreInit) return preInitCurrent ?? "En attente de la lecture…";
		if (state.displayMode === "fulltext") return currentText;
		if (!displayChunk) return currentText; // Fallback while meta is loading
		switch (state.displayMode) {
			case "keywords":
				return displayChunk.keywords.join(" — ");
			case "quote":
				return (
					displayChunk.quote_short || displayChunk.summary_short || currentText
				);
			case "summary":
				return displayChunk.summary_short || currentText;
			// Bridge modes fall back to their "primary" text when not rendered as dual layout
			case "summary_keywords":
			case "keywords_quote":
				return displayChunk.summary_short || currentText;
		}
		return currentText;
	};

	/** True when the mode is one of the "dual" bridge modes. */
	const isBridgeMode =
		state.displayMode === "summary_keywords" ||
		state.displayMode === "keywords_quote";

	/** Return keywords + secondary text for bridge modes. */
	const bridgeData = (() => {
		if (!displayChunk || !isBridgeMode) return null;
		const secondary =
			state.displayMode === "summary_keywords"
				? displayChunk.summary_short
				: displayChunk.quote_short;
		return {
			keywords: displayChunk.keywords,
			secondary: secondary || displayChunk.summary_short || currentText,
		};
	})();

	const showTopic =
		!isPreInit && state.displayMode !== "fulltext" && !!displayChunk?.topic;

	const onPickMode = (m: DisplayMode) =>
		setState((prev) => ({ ...prev, displayMode: m }));

	// ── Player button click handlers (placeholder — not wired yet) ─────────────
	const onPlay = () => {};
	const onPause = () => {};
	const onStop = () => {};
	const onSpeedUp = () => {};
	const onSpeedDown = () => {};

	return (
		<div className={styles.app}>
			<div className={styles.status}>
				<span className={styles.modeBadge}>{state.mode ?? "…"}</span>
				<span className={styles.displayModeBadge}>{state.displayMode}</span>
			</div>

			{showTopic && (
				<div className={styles.topicBar}>{displayChunk!.topic}</div>
			)}

			<div className={styles.stage}>
				{state.displayMode !== "fulltext" && (
					<div className={`${styles.ctx} ${styles.before}`}>
						{isPreInit ? "" : beforeText}
					</div>
				)}

				<div
					ref={bubbleRef}
					className={[
						styles.current,
						isPreInit ? styles.preInit : "",
						state.displayMode === "keywords" ? styles.keywords : "",
						isBridgeMode ? styles.bridge : "",
						state.displayMode === "fulltext" ? styles.fulltextSmall : "",
					]
						.filter(Boolean)
						.join(" ")}>
					{isBridgeMode && bridgeData ? (
						<div className={styles.bridgeInner}>
							<div className={styles.bridgeCapsules}>
								{bridgeData.keywords.join(" — ")}
							</div>
							<div className={styles.bridgeBody}>{bridgeData.secondary}</div>
						</div>
					) : (
						renderMain()
					)}
				</div>

				{state.displayMode !== "fulltext" && (
					<div className={`${styles.ctx} ${styles.after}`}>
						{isPreInit ? preInitAfter : afterText}
					</div>
				)}
			</div>

			<div className={styles.progressBar}>{progress}</div>

			{/*
        ── Bottom bar ────────────────────────────────────────────────────
        Left:   5 primary mode-selector buttons + separated "Texte exact"
        Right:  Player controls (visual only — not wired yet)
      */}
			<div className={styles.bottomBar}>
				<div className={styles.bottomSection}>
					<div className={styles.modeSelector} aria-label="Mode d'affichage">
						{PRIMARY_MODES.map((m) => {
							const isBridge =
								m === "summary_keywords" || m === "keywords_quote";
							return (
								<button
									key={m}
									type="button"
									className={[
										styles.modeButton,
										state.displayMode === m ? styles.modeButtonActive : "",
										isBridge ? styles.modeButtonBridge : "",
									]
										.filter(Boolean)
										.join(" ")}
									onClick={() => onPickMode(m)}
									aria-pressed={state.displayMode === m}
									title={MODE_LABEL[m]}>
									{isBridge ? (
										<>
											<span className={styles.modeButtonLabelBridge}>
												{MODE_LABEL[m]}
											</span>
											<span className={styles.modeButtonArrow}>↔</span>
										</>
									) : (
										<span className={styles.modeButtonLabel}>
											{MODE_LABEL[m]}
										</span>
									)}
								</button>
							);
						})}

						<span className={styles.modeSeparator} />

						<button
							type="button"
							className={[
								styles.modeButton,
								styles.modeButtonFulltext,
								state.displayMode === "fulltext" ? styles.modeButtonActive : "",
							]
								.filter(Boolean)
								.join(" ")}
							onClick={() => onPickMode("fulltext")}
							aria-pressed={state.displayMode === "fulltext"}
							title={MODE_LABEL.fulltext}>
							<span className={styles.modeButtonLabel}>
								{MODE_LABEL.fulltext}
							</span>
						</button>
					</div>
				</div>

				<div className={styles.bottomSection}>
					<div className={styles.player} aria-label="Contrôles de lecture">
						<button
							type="button"
							className={styles.playerBtn}
							onClick={onSpeedDown}
							title="Ralentir"
							aria-label="Ralentir la vitesse de lecture">
							−
						</button>
						<span className={styles.playerSpeed} aria-label="Vitesse actuelle">
							×1.0
						</span>
						<button
							type="button"
							className={styles.playerBtn}
							onClick={onSpeedUp}
							title="Accélérer"
							aria-label="Accélérer la vitesse de lecture">
							+
						</button>

						<div className={styles.playerDivider} />

						<button
							type="button"
							className={styles.playerBtn}
							onClick={onPlay}
							title="Lecture"
							aria-label="Lecture">
							▶
						</button>
						<button
							type="button"
							className={styles.playerBtn}
							onClick={onPause}
							title="Pause"
							aria-label="Pause">
							⏸
						</button>
						<button
							type="button"
							className={styles.playerBtn}
							onClick={onStop}
							title="Arrêter"
							aria-label="Arrêter la lecture">
							⏹
						</button>
					</div>
				</div>
			</div>

			<div className={`${styles.footer}${state.done ? ` ${styles.done}` : ""}`}>
				{footerText}
			</div>
		</div>
	);
}
