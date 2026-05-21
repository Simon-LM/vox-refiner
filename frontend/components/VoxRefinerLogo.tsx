/** @format */

import type { CSSProperties } from "react";

/**
 * Inline SVG logo. Colors are controlled via CSS custom properties:
 *   --logo-bg              background square     (default: #080808)
 *   --logo-dot             dot grid              (default: #181818)
 *   --logo-accent-start    gradient start        (default: #00FF88)
 *   --logo-accent-mid      gradient midpoint     (default: #00EE77)
 *   --logo-accent-end      gradient end          (default: #00CC66)
 *   --logo-separator       dashed divider        (default: #00FF88)
 */

interface VoxRefinerLogoProps {
	className?: string;
	style?: CSSProperties;
}

export default function VoxRefinerLogo({ className, style }: VoxRefinerLogoProps) {
	return (
		<svg
			viewBox="0 0 400 400"
			aria-label="VoxRefiner"
			role="img"
			className={className}
			style={style}
			xmlns="http://www.w3.org/2000/svg"
		>
			<defs>
				<linearGradient id="vr-morphGrad" x1="0%" y1="0%" x2="100%" y2="0%">
					<stop offset="0%"   style={{ stopColor: "var(--logo-accent-start, #00FF88)", stopOpacity: 1 }} />
					<stop offset="50%"  style={{ stopColor: "var(--logo-accent-mid,   #00EE77)", stopOpacity: 1 }} />
					<stop offset="100%" style={{ stopColor: "var(--logo-accent-end,   #00CC66)", stopOpacity: 1 }} />
				</linearGradient>

				<filter id="vr-glow" x="-0.0554" y="-0.0493" width="1.1108" height="1.0986">
					<feGaussianBlur stdDeviation="3" result="coloredBlur" />
					<feMerge>
						<feMergeNode in="coloredBlur" />
						<feMergeNode in="SourceGraphic" />
					</feMerge>
				</filter>

				<filter id="vr-subtleglow" x="-0.0456" y="-0.0419" width="1.0911" height="1.0837">
					<feGaussianBlur stdDeviation="1.5" result="coloredBlur" />
					<feMerge>
						<feMergeNode in="coloredBlur" />
						<feMergeNode in="SourceGraphic" />
					</feMerge>
				</filter>

				{/* Wave bars — left group */}
				<linearGradient href="#vr-morphGrad" id="vr-lg213" x1="80.9"  y1="40"  x2="110.6" y2="40"  gradientTransform="scale(0.3708,2.6968)" gradientUnits="userSpaceOnUse" />
				<linearGradient href="#vr-morphGrad" id="vr-lg215" x1="152.6" y1="27.7" x2="188.3" y2="27.7" gradientTransform="scale(0.3079,3.2474)" gradientUnits="userSpaceOnUse" />
				<linearGradient href="#vr-morphGrad" id="vr-lg217" x1="136.4" y1="57.7" x2="159.9" y2="57.7" gradientTransform="scale(0.4690,2.1320)" gradientUnits="userSpaceOnUse" />
				<linearGradient href="#vr-morphGrad" id="vr-lg219" x1="295.1" y1="20.6" x2="335.2" y2="20.6" gradientTransform="scale(0.2745,3.6432)" gradientUnits="userSpaceOnUse" />
				<linearGradient href="#vr-morphGrad" id="vr-lg221" x1="280.3" y1="36"   x2="311.8" y2="36"   gradientTransform="scale(0.3496,2.8604)" gradientUnits="userSpaceOnUse" />
				<linearGradient href="#vr-morphGrad" id="vr-lg223" x1="395.3" y1="24.1" x2="433.2" y2="24.1" gradientTransform="scale(0.2909,3.4378)" gradientUnits="userSpaceOnUse" />
				<linearGradient href="#vr-morphGrad" id="vr-lg225" x1="323.3" y1="46.9" x2="350.3" y2="46.9" gradientTransform="scale(0.4082,2.4495)" gradientUnits="userSpaceOnUse" />
				<linearGradient href="#vr-morphGrad" id="vr-lg227" x1="471.2" y1="29.4" x2="506"   y2="29.4" gradientTransform="scale(0.3162,3.1623)" gradientUnits="userSpaceOnUse" />

				{/* Transition bars */}
				<linearGradient href="#vr-morphGrad" id="vr-lg229" x1="496.3" y1="33.9" x2="528.8" y2="33.9" gradientTransform="scale(0.3385,2.9542)" gradientUnits="userSpaceOnUse" />
				<linearGradient href="#vr-morphGrad" id="vr-lg231" x1="479.8" y1="42.8" x2="508.4" y2="42.8" gradientTransform="scale(0.3855,2.5937)" gradientUnits="userSpaceOnUse" />
				<linearGradient href="#vr-morphGrad" id="vr-lg233" x1="413.1" y1="61.1" x2="435.6" y2="61.1" gradientTransform="scale(0.4890,2.0449)" gradientUnits="userSpaceOnUse" />
				<linearGradient href="#vr-morphGrad" id="vr-lg235" x1="336.7" y1="87.8" x2="353.6" y2="87.8" gradientTransform="scale(0.6504,1.5374)" gradientUnits="userSpaceOnUse" />
				<linearGradient href="#vr-morphGrad" id="vr-lg237" x1="246.5" y1="136"  x2="258"   y2="136"  gradientTransform="scale(0.9574,1.0445)" gradientUnits="userSpaceOnUse" />

				{/* Text lines — right group */}
				<linearGradient href="#vr-morphGrad" id="vr-lg239" x1="80.9"  y1="354.2" x2="116"   y2="354.2" gradientTransform="scale(3.1909,0.3134)" gradientUnits="userSpaceOnUse" />
				<linearGradient href="#vr-morphGrad" id="vr-lg241" x1="80.9"  y1="434"   x2="116"   y2="434"   gradientTransform="scale(3.1909,0.3134)" gradientUnits="userSpaceOnUse" />
				<linearGradient href="#vr-morphGrad" id="vr-lg243" x1="80.9"  y1="513.7" x2="116"   y2="513.7" gradientTransform="scale(3.1909,0.3134)" gradientUnits="userSpaceOnUse" />
				<linearGradient href="#vr-morphGrad" id="vr-lg245" x1="102.3" y1="469.2" x2="130"   y2="469.2" gradientTransform="scale(2.5226,0.3964)" gradientUnits="userSpaceOnUse" />

				<pattern id="vr-dots" width="18" height="18" patternUnits="userSpaceOnUse">
					<circle cx="9" cy="9" r="0.7" fill="var(--logo-dot, #181818)" />
				</pattern>
			</defs>

			{/* Background */}
			<rect width="400" height="400" rx="72" fill="var(--logo-bg, #080808)" />
			<rect width="400" height="400" rx="72" fill="url(#vr-dots)" />

			{/* Wave bars — left */}
			<g filter="url(#vr-glow)" transform="translate(0,50)">
				<rect x="30"  y="108" width="11" height="80"  rx="5.5" fill="url(#vr-lg213)" />
				<rect x="47"  y="90"  width="11" height="116" rx="5.5" fill="url(#vr-lg215)" />
				<rect x="64"  y="123" width="11" height="50"  rx="5.5" fill="url(#vr-lg217)" />
				<rect x="81"  y="75"  width="11" height="146" rx="5.5" fill="url(#vr-lg219)" />
				<rect x="98"  y="103" width="11" height="90"  rx="5.5" fill="url(#vr-lg221)" />
				<rect x="115" y="83"  width="11" height="130" rx="5.5" fill="url(#vr-lg223)" />
				<rect x="132" y="115" width="11" height="66"  rx="5.5" fill="url(#vr-lg225)" />
				<rect x="149" y="93"  width="11" height="110" rx="5.5" fill="url(#vr-lg227)" />
			</g>

			{/* Transition bars */}
			<g filter="url(#vr-subtleglow)" transform="translate(0,50)">
				<rect x="168" y="100" width="11" height="96" rx="5.5" fill="url(#vr-lg229)" opacity="0.95" />
				<rect x="185" y="111" width="11" height="74" rx="5.5" fill="url(#vr-lg231)" opacity="0.88" />
				<rect x="202" y="125" width="11" height="46" rx="5.5" fill="url(#vr-lg233)" opacity="0.80" />
				<rect x="219" y="135" width="11" height="26" rx="5.5" fill="url(#vr-lg235)" opacity="0.72" />
				<rect x="236" y="142" width="11" height="12" rx="5.5" fill="url(#vr-lg237)" opacity="0.65" />
			</g>

			{/* Text lines — right */}
			<g filter="url(#vr-subtleglow)" transform="translate(0,50)">
				<rect x="258" y="111" width="112" height="11" rx="5.5" fill="url(#vr-lg239)" opacity="0.95" />
				<rect x="258" y="136" width="112" height="11" rx="5.5" fill="url(#vr-lg241)" opacity="0.85" />
				<rect x="258" y="161" width="112" height="11" rx="5.5" fill="url(#vr-lg243)" opacity="0.75" />
				<rect x="258" y="186" width="70"  height="11" rx="5.5" fill="url(#vr-lg245)" opacity="0.50" />
			</g>

			{/* Dashed divider */}
			<line
				x1="250" y1="68" x2="250" y2="218"
				stroke="var(--logo-separator, #00FF88)"
				strokeWidth="1"
				opacity="0.10"
				strokeDasharray="4 5"
			/>
		</svg>
	);
}
