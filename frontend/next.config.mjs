import { createMDX } from 'fumadocs-mdx/next';

const withMDX = createMDX();

/** @type {import('next').NextConfig} */
const config = {
  reactStrictMode: true,
  // No basePath: the landing page owns `/` and the docs live at `/docs` as
  // real routes in the same app. The two used to be separate deployments
  // stitched together by Vercel routing rules, which is what kept breaking.
  typescript: {
    ignoreBuildErrors: true,
  },
};

export default withMDX(config);
