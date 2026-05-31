import { defineConfig } from 'vite';
import { resolve } from 'path';

export default defineConfig({
  root: resolve(__dirname, '..'),
  build: {
    outDir: resolve(__dirname, '../docs/assets/js'),
    emptyOutDir: false,
    rollupOptions: {
      input: resolve(__dirname, 'src/manta_case_viewer.js'),
      output: {
        entryFileNames: 'manta_case_viewer.bundle.js',
        chunkFileNames: 'manta_case_viewer.[name].js',
        assetFileNames: 'manta_case_viewer.[name][extname]',
      },
    },
  },
});
