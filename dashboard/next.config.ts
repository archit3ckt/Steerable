import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // A self-contained server for the container image (Dockerfile sets it).
  output: process.env.NEXT_OUTPUT === "standalone" ? "standalone" : undefined,
  cacheComponents: true,
  experimental: {
    // proxy.ts sees every request (it checks the sign-in), and buffers bodies up to this size;
    // chat attachments are up to 20 MB, and a company brought into a new space (Spaces) up to 500 MB.
    proxyClientMaxBodySize: "500mb",
  },
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
