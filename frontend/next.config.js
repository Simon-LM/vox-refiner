/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'export',
  images: { unoptimized: true },
  sassOptions: {
    includePaths: ['./styles'],
  },
};

module.exports = nextConfig;
