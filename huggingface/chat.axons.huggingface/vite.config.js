import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  define: {
    'process.env.NODE_ENV': JSON.stringify('production'),
  },
  build: {
    lib: {
      entry: 'src/index.tsx',
      formats: ['es'],
      fileName: () => 'index.js',
    },
    rollupOptions: {
      // 外部化：复用 axons 运行时已有的 React，不打包进插件产物
      external: ['react', 'react-dom', 'axons-plugin-ui'],
      output: {
        globals: {
          react: 'React',
          'react-dom': 'ReactDOM',
          'axons-plugin-ui': 'AxonsPluginUI',
        },
      },
    },
    outDir: 'ui',
    emptyOutDir: false, // 保留 ui/icon.svg
  },
});
