// Render the app icon SVG into the PNG sizes phones need (run once: `node scripts/make-icons.mjs`).
import { fileURLToPath } from 'node:url'
import sharp from 'sharp'

const svg = fileURLToPath(new URL('../public/icon.svg', import.meta.url))
const out = (name) => fileURLToPath(new URL(`../public/${name}`, import.meta.url))
for (const [size, name] of [[192, 'icon-192.png'], [512, 'icon-512.png'], [180, 'apple-touch-icon.png']]) {
  await sharp(svg, { density: 384 }).resize(size, size).png().toFile(out(name))
  console.log('wrote', name)
}
