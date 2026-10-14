/**
 * Light or dark: the device's choice unless the owner picked one (the theme switch). The pick
 * lives in localStorage and becomes data-theme on <html>, which theme.css reads. Hosts put
 * THEME_SCRIPT first in <head>, so the page never flashes the wrong theme:
 *
 *   <html suppressHydrationWarning><head><script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} /></head>
 */

export type Theme = "auto" | "light" | "dark";
export const THEME_KEY = "steerable-theme";

export const THEME_SCRIPT = `try{var t=localStorage.getItem("${THEME_KEY}");if(t==="light"||t==="dark")document.documentElement.dataset.theme=t}catch(e){}`;
