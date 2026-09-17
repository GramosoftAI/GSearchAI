import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  allowedDevOrigins: ['192.168.1.150', '192.168.1.14:3000', '192.168.1.14', '192.168.0.119', '192.168.0.108', '192.168.31.86', '192.168.1.33'],
  /* config options here */
  images: {
    remotePatterns: [
      {
        protocol: "https",
        hostname: "cdn-icons-png.flaticon.com",
      },
      {
        protocol: "https",
        hostname: "img.icons8.com",
      },
    ],
  },

};

export default nextConfig;
