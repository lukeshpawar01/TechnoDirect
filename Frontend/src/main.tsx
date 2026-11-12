import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import axios from 'axios';
import dayjs from 'dayjs';
import 'dayjs/locale/en-in';
import { ThemeProvider } from '@/lib/theme';
import { AuthProvider } from '@/auth/AuthContext';
import App from './App';
import './index.css';

dayjs.locale('en-in');

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      // Data refreshes at 10:00 / 18:00 IST — never refetch just because the tab regained focus.
      refetchOnWindowFocus: false,
      retry: (count, err) => {
        const s = axios.isAxiosError(err) ? err.response?.status : undefined;
        if (s && s >= 400 && s < 500) return false; // auth / permission / not found: don't hammer
        return count < 2;
      },
    },
  },
});

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ThemeProvider>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <AuthProvider>
            <App />
          </AuthProvider>
        </BrowserRouter>
      </QueryClientProvider>
    </ThemeProvider>
  </React.StrictMode>,
);
