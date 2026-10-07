import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // output: 'standalone' genera una imagen Docker mínima (~50 MB vs ~500 MB)
  // copiando solo los artefactos necesarios. No afecta al modo dev.
  output: "standalone",
};

export default nextConfig;
