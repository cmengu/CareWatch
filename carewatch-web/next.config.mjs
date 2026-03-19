const nextConfig = {
  async redirects() {
    return [
      { source: '/', destination: '/dashboard.html', permanent: false }
    ]
  }
}
export default nextConfig;
