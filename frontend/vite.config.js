import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
  ],
  build: {
    rolldownOptions: {
      output: {
        // Big libraries get their own files: they change rarely, so the browser
        // keeps them cached when only our code changes. Every page is a separate
        // lazy chunk (see App.jsx); the force graph library loads only on People.
        codeSplitting: {
          groups: [
            { name: 'react', test: /node_modules[\\/](react|react-dom|react-router|react-router-dom|scheduler)[\\/]/, priority: 30 },
            { name: 'firebase', test: /node_modules[\\/](@firebase|firebase)[\\/]/, priority: 20 },
            { name: 'motion', test: /node_modules[\\/](framer-motion|motion-dom|motion-utils|lenis)[\\/]/, priority: 20 },
          ],
        },
      },
    },
  },
})
