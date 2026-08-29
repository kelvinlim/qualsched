/// <reference types="vite/client" />

// `import.meta.env.BASE_URL` is Vite `base`: `/` locally, `/qualsched/` in the
// production frontend image. Join app `/api` `/auth` `/health` paths with it.

declare module "@qualsched/changelog?raw" {
  const src: string;
  export default src;
}

declare module "@qualsched/guide?raw" {
  const src: string;
  export default src;
}

