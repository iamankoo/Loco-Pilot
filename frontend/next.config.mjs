/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // This repo never tracks coding-agent instruction files (see .gitignore);
  // disable Next.js's auto-generated ones instead of relying on gitignore
  // alone to keep them out of the working tree.
  agentRules: false,
  turbopack: {
    root: import.meta.dirname,
  },
};

export default nextConfig;
