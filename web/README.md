# MemStack Web Console

Modern React-based web console for MemStack - Enterprise AI Memory Cloud Platform.

## Features

- 📊 Dashboard with system overview
- 📝 Episode creation and management
- 🔍 Natural language memory search
- 🕸️ Knowledge graph visualization (Cytoscape.js)
- ⚙️ API key configuration
- 🎨 Modern UI with Ant Design

## Tech Stack

- **React 18** with TypeScript
- **Vite** for fast development and building
- **Ant Design** for UI components
- **React Router** for navigation
- **Axios** for API calls
- **Cytoscape.js** for graph visualization

## Development

### Prerequisites

- Node.js 18+ and npm/yarn
- Running MemStack API server (default: http://localhost:8000)

### Install Dependencies

```bash
npm install
```

### Start Development Server

```bash
npm run dev
```

The web console will be available at http://localhost:3000

### Build for Production

```bash
npm run build
```

The production build will be in the `dist/` directory.

### Preview Production Build

```bash
npm run preview
```

## Configuration

### API Endpoint

The web console connects to the MemStack API. During development, the API is proxied through Vite:

```typescript
// vite.config.ts
server: {
  proxy: {
    '/api': {
      target: 'http://localhost:8000',
      changeOrigin: true,
    },
  },
}
```

For production, configure your reverse proxy (nginx) to route `/api` requests to the backend.

### API Key

On first use, navigate to Settings and enter your API key. The key is stored in localStorage and automatically included in all API requests.

## Project Structure

```
web/
├── src/
│   ├── components/      # Reusable React components
│   │   └── Layout.tsx
│   ├── pages/          # Page components
│   │   ├── Dashboard.tsx
│   │   ├── Episodes.tsx
│   │   ├── Search.tsx
│   │   ├── GraphView.tsx
│   │   └── Settings.tsx
│   ├── services/       # API client and services
│   │   └── api.ts
│   ├── App.tsx         # Main app component
│   ├── main.tsx        # Entry point
│   └── index.css       # Global styles
├── index.html
├── package.json
├── tsconfig.json
└── vite.config.ts
```

## Docker Deployment

### Build Docker Image

```bash
docker build -t memstack-web .
```

### Run Container

```bash
docker run -p 80:80 memstack-web
```

### Docker Compose

```yaml
version: '3.8'
services:
  web:
    build: ./web
    ports:
      - "80:80"
    environment:
      - API_BASE_URL=http://api:8000
```

## Usage Guide

### 1. Configure API Key

1. Navigate to Settings
2. Enter your MemStack API key (starts with `ms_sk_`)
3. Click "Save Settings"

### 2. Create Episodes

1. Go to Episodes page
2. Fill in episode details:
   - Name: Descriptive name
   - Content: Text or JSON data
   - Source Type: text or json
   - Group ID (optional): For organizing episodes
3. Click "Create Episode"

### 3. Search Memories

1. Go to Search page
2. Enter natural language query
3. View results with relevance scores

### 4. Visualize Knowledge Graph

1. Go to Knowledge Graph page
2. Explore nodes and relationships
3. Interact with the graph (zoom, pan, click)

## Development Tips

### Hot Module Replacement

Vite provides instant HMR. Changes to React components will reflect immediately without losing state.

### Type Safety

The project uses TypeScript with strict mode enabled. All API interfaces are typed for safety.

### Linting

```bash
npm run lint
```

### Testing

```bash
npm run test
```

## Troubleshooting

### CORS Issues

If you encounter CORS errors, ensure your API server has CORS properly configured:

```python
# server/main.py
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # Add your web origin
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

### API Connection Failed

1. Check that the API server is running
2. Verify the API URL in Settings
3. Check browser console for error messages
4. Ensure your API key is valid

### Build Errors

```bash
# Clear node_modules and reinstall
rm -rf node_modules package-lock.json
npm install
```

## License

MIT
