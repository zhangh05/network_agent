// vite.config.ts
import { defineConfig, loadEnv } from "file:///Users/zhangh01/Desktop/network_agent/frontend/node_modules/vite/dist/node/index.js";
import react from "file:///Users/zhangh01/Desktop/network_agent/frontend/node_modules/@vitejs/plugin-react/dist/index.js";
var vite_config_default = defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const devApiTarget = env.VITE_DEV_API_TARGET || "http://127.0.0.1:8010";
  return {
    plugins: [react()],
    server: {
      host: "0.0.0.0",
      port: 5173,
      proxy: {
        "/api": {
          target: devApiTarget,
          changeOrigin: true
        },
        "/ws": {
          target: devApiTarget,
          ws: true,
          changeOrigin: true
        }
      }
    },
    test: {
      globals: true,
      environment: "happy-dom",
      setupFiles: "./src/test/setup.ts",
      css: false,
      include: ["src/**/*.{test,spec}.{ts,tsx}"],
      exclude: ["e2e/**", "node_modules/**", "dist/**"]
    },
    build: {
      // The workbench is a single-screen console; after trimming highlight.js to
      // registered languages, the main chunk is expected to sit just above
      // Vite's generic 500 kB warning threshold.
      chunkSizeWarningLimit: 700,
      rollupOptions: {
        output: {
          // Split the React core into its own long-lived vendor chunk so it is
          // cached independently of page chunks and the app shell. Page chunks
          // produced by route-level code splitting carry only their own code.
          manualChunks(id) {
            if (id.includes("node_modules")) {
              if (/[\\/]node_modules[\\/](react|react-dom|react-router|react-router-dom|scheduler)[\\/]/.test(
                id
              )) {
                return "vendor-react";
              }
            }
          }
        }
      }
    }
  };
});
export {
  vite_config_default as default
};
//# sourceMappingURL=data:application/json;base64,ewogICJ2ZXJzaW9uIjogMywKICAic291cmNlcyI6IFsidml0ZS5jb25maWcudHMiXSwKICAic291cmNlc0NvbnRlbnQiOiBbImNvbnN0IF9fdml0ZV9pbmplY3RlZF9vcmlnaW5hbF9kaXJuYW1lID0gXCIvVXNlcnMvemhhbmdoMDEvRGVza3RvcC9uZXR3b3JrX2FnZW50L2Zyb250ZW5kXCI7Y29uc3QgX192aXRlX2luamVjdGVkX29yaWdpbmFsX2ZpbGVuYW1lID0gXCIvVXNlcnMvemhhbmdoMDEvRGVza3RvcC9uZXR3b3JrX2FnZW50L2Zyb250ZW5kL3ZpdGUuY29uZmlnLnRzXCI7Y29uc3QgX192aXRlX2luamVjdGVkX29yaWdpbmFsX2ltcG9ydF9tZXRhX3VybCA9IFwiZmlsZTovLy9Vc2Vycy96aGFuZ2gwMS9EZXNrdG9wL25ldHdvcmtfYWdlbnQvZnJvbnRlbmQvdml0ZS5jb25maWcudHNcIjsvLy8gPHJlZmVyZW5jZSB0eXBlcz1cInZpdGVzdFwiIC8+XG4vLy8gPHJlZmVyZW5jZSB0eXBlcz1cIm5vZGVcIiAvPlxuaW1wb3J0IHsgZGVmaW5lQ29uZmlnLCBsb2FkRW52IH0gZnJvbSBcInZpdGVcIjtcbmltcG9ydCByZWFjdCBmcm9tIFwiQHZpdGVqcy9wbHVnaW4tcmVhY3RcIjtcblxuLyoqXG4gKiBWaXRlIGNvbmZpZy5cbiAqXG4gKiBEZXYgcHJveHkgKG5wbSBydW4gZGV2KTpcbiAqICAtIGAvYXBpYCBcdTIxOTIgYFZJVEVfREVWX0FQSV9UQVJHRVRgIChkZWZhdWx0IGBodHRwOi8vMTI3LjAuMC4xOjgwMTBgKVxuICpcbiAqIFByb2R1Y3Rpb24gYnVpbGQgKG5wbSBydW4gYnVpbGQpOlxuICogIC0gU3RhdGljIGZpbGVzIGluIGBkaXN0L2AgY2FuIGJlIHNlcnZlZCBieSB0aGUgRmxhc2sgYmFja2VuZFxuICogICAgb3IgYnkgYSBzZXBhcmF0ZSBzdGF0aWMgc2VydmVyLiBUaGUgZnJvbnRlbmQncyBBUEkgYmFzZSBVUkxcbiAqICAgIGlzIHJlYWQgZnJvbSBgVklURV9BUElfQkFTRWAgYXQgYnVpbGQgdGltZSwgZGVmYXVsdGluZyB0b1xuICogICAgYC9hcGlgIChzYW1lLW9yaWdpbikuIE92ZXJyaWRlIHBlci1lbnZpcm9ubWVudCB2aWFcbiAqICAgIGBWSVRFX0FQSV9CQVNFPWh0dHBzOi8vZXhhbXBsZS5jb21gIGV0Yy5cbiAqL1xuZXhwb3J0IGRlZmF1bHQgZGVmaW5lQ29uZmlnKCh7IG1vZGUgfSkgPT4ge1xuICBjb25zdCBlbnYgPSBsb2FkRW52KG1vZGUsIHByb2Nlc3MuY3dkKCksIFwiXCIpO1xuICBjb25zdCBkZXZBcGlUYXJnZXQgPSBlbnYuVklURV9ERVZfQVBJX1RBUkdFVCB8fCBcImh0dHA6Ly8xMjcuMC4wLjE6ODAxMFwiO1xuXG4gIHJldHVybiB7XG4gICAgcGx1Z2luczogW3JlYWN0KCldLFxuICAgIHNlcnZlcjoge1xuICAgICAgaG9zdDogXCIwLjAuMC4wXCIsXG4gICAgICBwb3J0OiA1MTczLFxuICAgICAgcHJveHk6IHtcbiAgICAgICAgXCIvYXBpXCI6IHtcbiAgICAgICAgICB0YXJnZXQ6IGRldkFwaVRhcmdldCxcbiAgICAgICAgICBjaGFuZ2VPcmlnaW46IHRydWUsXG4gICAgICAgIH0sXG4gICAgICAgIFwiL3dzXCI6IHtcbiAgICAgICAgICB0YXJnZXQ6IGRldkFwaVRhcmdldCxcbiAgICAgICAgICB3czogdHJ1ZSxcbiAgICAgICAgICBjaGFuZ2VPcmlnaW46IHRydWUsXG4gICAgICAgIH0sXG4gICAgICB9LFxuICAgIH0sXG4gICAgdGVzdDoge1xuICAgICAgZ2xvYmFsczogdHJ1ZSxcbiAgICAgIGVudmlyb25tZW50OiBcImhhcHB5LWRvbVwiLFxuICAgICAgc2V0dXBGaWxlczogXCIuL3NyYy90ZXN0L3NldHVwLnRzXCIsXG4gICAgICBjc3M6IGZhbHNlLFxuICAgICAgaW5jbHVkZTogW1wic3JjLyoqLyoue3Rlc3Qsc3BlY30ue3RzLHRzeH1cIl0sXG4gICAgICBleGNsdWRlOiBbXCJlMmUvKipcIiwgXCJub2RlX21vZHVsZXMvKipcIiwgXCJkaXN0LyoqXCJdLFxuICAgIH0sXG4gICAgYnVpbGQ6IHtcbiAgICAgIC8vIFRoZSB3b3JrYmVuY2ggaXMgYSBzaW5nbGUtc2NyZWVuIGNvbnNvbGU7IGFmdGVyIHRyaW1taW5nIGhpZ2hsaWdodC5qcyB0b1xuICAgICAgLy8gcmVnaXN0ZXJlZCBsYW5ndWFnZXMsIHRoZSBtYWluIGNodW5rIGlzIGV4cGVjdGVkIHRvIHNpdCBqdXN0IGFib3ZlXG4gICAgICAvLyBWaXRlJ3MgZ2VuZXJpYyA1MDAga0Igd2FybmluZyB0aHJlc2hvbGQuXG4gICAgICBjaHVua1NpemVXYXJuaW5nTGltaXQ6IDcwMCxcbiAgICAgIHJvbGx1cE9wdGlvbnM6IHtcbiAgICAgICAgb3V0cHV0OiB7XG4gICAgICAgICAgLy8gU3BsaXQgdGhlIFJlYWN0IGNvcmUgaW50byBpdHMgb3duIGxvbmctbGl2ZWQgdmVuZG9yIGNodW5rIHNvIGl0IGlzXG4gICAgICAgICAgLy8gY2FjaGVkIGluZGVwZW5kZW50bHkgb2YgcGFnZSBjaHVua3MgYW5kIHRoZSBhcHAgc2hlbGwuIFBhZ2UgY2h1bmtzXG4gICAgICAgICAgLy8gcHJvZHVjZWQgYnkgcm91dGUtbGV2ZWwgY29kZSBzcGxpdHRpbmcgY2Fycnkgb25seSB0aGVpciBvd24gY29kZS5cbiAgICAgICAgICBtYW51YWxDaHVua3MoaWQpIHtcbiAgICAgICAgICAgIGlmIChpZC5pbmNsdWRlcyhcIm5vZGVfbW9kdWxlc1wiKSkge1xuICAgICAgICAgICAgICBpZiAoXG4gICAgICAgICAgICAgICAgL1tcXFxcL11ub2RlX21vZHVsZXNbXFxcXC9dKHJlYWN0fHJlYWN0LWRvbXxyZWFjdC1yb3V0ZXJ8cmVhY3Qtcm91dGVyLWRvbXxzY2hlZHVsZXIpW1xcXFwvXS8udGVzdChcbiAgICAgICAgICAgICAgICAgIGlkLFxuICAgICAgICAgICAgICAgIClcbiAgICAgICAgICAgICAgKSB7XG4gICAgICAgICAgICAgICAgcmV0dXJuIFwidmVuZG9yLXJlYWN0XCI7XG4gICAgICAgICAgICAgIH1cbiAgICAgICAgICAgIH1cbiAgICAgICAgICB9LFxuICAgICAgICB9LFxuICAgICAgfSxcbiAgICB9LFxuICB9O1xufSk7XG4iXSwKICAibWFwcGluZ3MiOiAiO0FBRUEsU0FBUyxjQUFjLGVBQWU7QUFDdEMsT0FBTyxXQUFXO0FBZWxCLElBQU8sc0JBQVEsYUFBYSxDQUFDLEVBQUUsS0FBSyxNQUFNO0FBQ3hDLFFBQU0sTUFBTSxRQUFRLE1BQU0sUUFBUSxJQUFJLEdBQUcsRUFBRTtBQUMzQyxRQUFNLGVBQWUsSUFBSSx1QkFBdUI7QUFFaEQsU0FBTztBQUFBLElBQ0wsU0FBUyxDQUFDLE1BQU0sQ0FBQztBQUFBLElBQ2pCLFFBQVE7QUFBQSxNQUNOLE1BQU07QUFBQSxNQUNOLE1BQU07QUFBQSxNQUNOLE9BQU87QUFBQSxRQUNMLFFBQVE7QUFBQSxVQUNOLFFBQVE7QUFBQSxVQUNSLGNBQWM7QUFBQSxRQUNoQjtBQUFBLFFBQ0EsT0FBTztBQUFBLFVBQ0wsUUFBUTtBQUFBLFVBQ1IsSUFBSTtBQUFBLFVBQ0osY0FBYztBQUFBLFFBQ2hCO0FBQUEsTUFDRjtBQUFBLElBQ0Y7QUFBQSxJQUNBLE1BQU07QUFBQSxNQUNKLFNBQVM7QUFBQSxNQUNULGFBQWE7QUFBQSxNQUNiLFlBQVk7QUFBQSxNQUNaLEtBQUs7QUFBQSxNQUNMLFNBQVMsQ0FBQywrQkFBK0I7QUFBQSxNQUN6QyxTQUFTLENBQUMsVUFBVSxtQkFBbUIsU0FBUztBQUFBLElBQ2xEO0FBQUEsSUFDQSxPQUFPO0FBQUE7QUFBQTtBQUFBO0FBQUEsTUFJTCx1QkFBdUI7QUFBQSxNQUN2QixlQUFlO0FBQUEsUUFDYixRQUFRO0FBQUE7QUFBQTtBQUFBO0FBQUEsVUFJTixhQUFhLElBQUk7QUFDZixnQkFBSSxHQUFHLFNBQVMsY0FBYyxHQUFHO0FBQy9CLGtCQUNFLHVGQUF1RjtBQUFBLGdCQUNyRjtBQUFBLGNBQ0YsR0FDQTtBQUNBLHVCQUFPO0FBQUEsY0FDVDtBQUFBLFlBQ0Y7QUFBQSxVQUNGO0FBQUEsUUFDRjtBQUFBLE1BQ0Y7QUFBQSxJQUNGO0FBQUEsRUFDRjtBQUNGLENBQUM7IiwKICAibmFtZXMiOiBbXQp9Cg==
