const IMAGE_TYPES = ["image/png", "image/jpeg", "image/webp", "image/gif"];
const IMAGE_MAX_SIDE = 1024;
const IMAGE_MAX_BYTES = 1024 * 1024;

const readFile = (file) => new Promise((resolve, reject) => {
  const reader = new FileReader();
  reader.onload = () => resolve(reader.result);
  reader.onerror = () => reject(new Error("That file could not be read."));
  reader.readAsDataURL(file);
});

export async function shrinkImage(file) {
  if (!IMAGE_TYPES.includes(file.type)) throw new Error("Choose a PNG, JPEG, WebP or GIF image.");
  const src = await readFile(file);
  const img = new Image();
  img.src = src;
  try {
    await img.decode();
  } catch {
    throw new Error("That file is not a valid image.");
  }
  const side = Math.max(img.naturalWidth, img.naturalHeight);
  if (file.size <= IMAGE_MAX_BYTES && side <= IMAGE_MAX_SIDE) return src;
  const scale = Math.min(1, IMAGE_MAX_SIDE / side);
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.round(img.naturalWidth * scale));
  canvas.height = Math.max(1, Math.round(img.naturalHeight * scale));
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = "#fff";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
  for (const quality of [0.85, 0.7, 0.5]) {
    const out = canvas.toDataURL("image/jpeg", quality);
    if ((out.length - out.indexOf(",") - 1) * 0.75 <= IMAGE_MAX_BYTES) return out;
  }
  throw new Error("That photo is still too large after resizing. Try a smaller image.");
}
