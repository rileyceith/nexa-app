import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";

createRoot(document.getElementById("root")).render(<App />);

const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
const video = document.getElementById("orb");
if (reduce) {
  video.removeAttribute("autoplay");
  video.pause();
} else {
  const playback = video.play();
  if (playback && playback.catch) playback.catch(() => {});
  addEventListener("pointermove", (event) => {
    const root = document.documentElement.style;
    root.setProperty("--px", ((event.clientX / innerWidth - 0.5) * 28) + "px");
    root.setProperty("--py", ((event.clientY / innerHeight - 0.5) * 20) + "px");
  });
}
