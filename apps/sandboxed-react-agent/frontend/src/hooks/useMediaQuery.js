import { useEffect, useState } from "react";

const getMatches = (query, fallback = false) => {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return fallback;
  }
  return window.matchMedia(query).matches;
};

export function useMediaQuery(query, fallback = false) {
  const [matches, setMatches] = useState(() => getMatches(query, fallback));

  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
      return undefined;
    }
    const media = window.matchMedia(query);
    const onChange = (event) => setMatches(event.matches);
    setMatches(media.matches);
    if (typeof media.addEventListener === "function") {
      media.addEventListener("change", onChange);
      return () => media.removeEventListener("change", onChange);
    }
    media.addListener(onChange);
    return () => media.removeListener(onChange);
  }, [query]);

  return matches;
}
