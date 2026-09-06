import type { NextConfig } from "next";

const configuredApiOrigin = process.env.RIPPLE_API_ORIGIN?.replace(/\/$/, "");
const apiOrigin = configuredApiOrigin
  ? /^https?:\/\//.test(configuredApiOrigin)
    ? configuredApiOrigin
    : `http://${configuredApiOrigin}`
  : null;

const nextConfig: NextConfig = {
  // Hide the Next.js dev-tools indicator (the floating "N" badge) so
  // screenshots of the app are clean.
  devIndicators: false,
  async rewrites() {
    if (!apiOrigin) return [];
    return [
      {
        source: "/api/v1/:path*",
        destination: `${apiOrigin}/api/v1/:path*`,
      },
    ];
  },
};

export default nextConfig;
