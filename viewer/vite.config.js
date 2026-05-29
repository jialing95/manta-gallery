import { defineConfig } from 'vite';
import { resolve } from 'path';

export default defineConfig({
  root: resolve(__dirname, '..'),
  build: {
    outDir: resolve(__dirname, '../docs/assets/js'),
    emptyOutDir: false,
    rollupOptions: {
      input: resolve(__dirname, 'src/aqaba_case_001_viewer.js'),
      output: {
        entryFileNames: 'aqaba_case_001_viewer.bundle.js',
        chunkFileNames: 'aqaba_case_001_viewer.[name].js',
        assetFileNames: 'aqaba_case_001_viewer.[name][extname]',
      },
    },
  },
});
