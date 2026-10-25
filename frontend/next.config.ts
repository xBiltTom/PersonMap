import type { NextConfig } from "next";

const apiTarget = (
  process.env.API_PROXY_TARGET || "http://127.0.0.1:8000"
).replace(/\/$/, "");

const nextConfig: NextConfig = {
  // output: 'standalone' genera una imagen Docker mínima (~50 MB vs ~500 MB)
  // copiando solo los artefactos necesarios. No afecta al modo dev.
  output: "standalone",
  allowedDevOrigins: (process.env.DEV_ALLOWED_ORIGINS || "")
    .split(",")
    .map((origin) => origin.trim())
    .filter(Boolean),
  async rewrites() {
    return [
      { source: "/api/v1/:path*", destination: `${apiTarget}/api/v1/:path*` },
      { source: "/health", destination: `${apiTarget}/health` },
    ];
  },
};

export default nextConfig;
