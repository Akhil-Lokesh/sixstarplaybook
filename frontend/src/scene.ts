// The hero backdrop: striped sunset sun, skyline and palm silhouettes. Original art, drawn in code.

function skyline(): string {
  // A deterministic pseudo-random skyline so the build is stable.
  let seed = 11;
  const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
  const H = 170;
  let x = 0;
  let d = `M0 ${H}`;
  let windows = "";
  while (x < 1200) {
    const w = 16 + rnd() * 44;
    const h = 22 + Math.pow(rnd(), 2.2) * 135;
    const top = H - h;
    d += `L${x.toFixed(1)} ${top.toFixed(1)}L${(x + w).toFixed(1)} ${top.toFixed(1)}`;
    if (h > 55) {
      const cols = Math.floor(w / 9);
      for (let c = 0; c < cols; c++) {
        for (let r = 0; r < Math.floor(h / 13) - 1; r++) {
          if (rnd() < 0.16) {
            const fill = rnd() < 0.5 ? "#FFD166" : "#FF3D7F";
            windows += `<rect x="${(x + 4 + c * 9).toFixed(1)}" y="${(top + 8 + r * 13).toFixed(1)}" width="3" height="4" fill="${fill}" opacity="${(0.35 + rnd() * 0.5).toFixed(2)}"/>`;
          }
        }
      }
    }
    x += w;
  }
  d += `L1200 ${H}Z`;
  return `<svg class="skyline" viewBox="0 0 1200 ${H}" preserveAspectRatio="none" aria-hidden="true"><path d="${d}" fill="#0A0715"/>${windows}</svg>`;
}

const PALM = `
<symbol id="palm" viewBox="0 0 120 230">
  <path d="M55 230 C50 170 66 120 59 64 L65 64 C73 120 58 172 64 230Z"/>
  <path d="M61 64 Q30 26 0 54 Q32 42 61 64Z"/>
  <path d="M61 64 Q38 14 8 16 Q40 26 61 64Z"/>
  <path d="M61 64 Q60 18 40 0 Q54 30 61 64Z"/>
  <path d="M61 64 Q76 14 106 8 Q80 28 61 64Z"/>
  <path d="M61 64 Q94 30 120 52 Q90 42 61 64Z"/>
  <path d="M61 64 Q92 56 112 94 Q88 66 61 64Z"/>
  <path d="M61 64 Q30 58 12 96 Q34 68 61 64Z"/>
</symbol>`;

export function sceneHTML(): string {
  return `
<div class="scene" aria-hidden="true">
  <div class="stars"></div>
  <div class="sun-glow"></div>
  <div class="sun"></div>
  ${skyline()}
  <svg class="palms" viewBox="0 0 1200 230" preserveAspectRatio="xMidYMax slice">
    <defs>${PALM}</defs>
    <g fill="#07050F">
      <use href="#palm" x="20" y="10" width="120" height="230"/>
      <use href="#palm" x="118" y="70" width="84" height="161"/>
      <use href="#palm" x="1010" y="40" width="100" height="192"/>
      <use href="#palm" x="1090" y="0" width="120" height="230"/>
    </g>
  </svg>
  <div class="water"></div>
</div>`;
}
