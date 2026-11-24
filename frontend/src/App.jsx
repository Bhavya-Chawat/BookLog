import { Suspense, lazy, useEffect } from 'react';
import { BrowserRouter as Router, Navigate, Route, Routes, useLocation } from 'react-router-dom';
import Navbar, { NAV } from './components/Navbar';
import Footer from './components/Footer';
import { CommandPalette, Intro, PageTransition, SmoothScroll } from './components/shell';
import { OnboardingGate } from './components/GenrePicker';
import { AuthProvider } from './contexts/AuthContext';
import { PulseProvider } from './components/social';
import { Spinner } from './components/ui';

// Every page is its own file, downloaded the first time it is opened,
// so the first visit only loads the app shell and the page you land on.
const HomePage = lazy(() => import('./pages/HomePage'));
const LandingPage = lazy(() => import('./pages/LandingPage'));
const ExplorePage = lazy(() => import('./pages/ExplorePage'));
const SearchPage = lazy(() => import('./pages/SearchPage'));
const BookDetailsPage = lazy(() => import('./pages/BookDetailsPage'));
const AuthorDetailsPage = lazy(() => import('./pages/AuthorDetailsPage'));
const ListsPage = lazy(() => import('./pages/ListsPage'));
const NewListPage = lazy(() => import('./pages/ListsPage').then((m) => ({ default: m.NewListPage })));
const MyLibraryPage = lazy(() => import('./pages/MyLibraryPage'));
const ListDetailPage = lazy(() => import('./pages/ListDetailPage'));
const FeedPage = lazy(() => import('./pages/FeedPage'));
const PeoplePage = lazy(() => import('./pages/PeoplePage'));
const ProfilePage = lazy(() => import('./pages/ProfilePage'));
const StatsPage = lazy(() => import('./pages/StatsPage'));
const SettingsPage = lazy(() => import('./pages/SettingsPage'));
const ChatPage = lazy(() => import('./pages/ChatPage'));
const AdminPage = lazy(() => import('./pages/AdminPage'));
const FlipsPage = lazy(() => import('./pages/FlipsPage'));
const MessagesPage = lazy(() => import('./pages/MessagesPage'));
const QuizPage = lazy(() => import('./pages/QuizPage'));

// Each page gets its own paper colour (palettes live in index.css)
const PAGE_COLOURS = [
  ['/explore', 'sky'], ['/flips', 'steel'], ['/lists', 'pink'], ['/quiz', 'lime'],
  ['/search', 'blush'], ['/author', 'rose'], ['/library', 'pink'], ['/feed', 'sky'],
  ['/people', 'lime'], ['/messages', 'blush'], ['/chat', 'sky'], ['/u/', 'rose'],
];
const pageColour = (path) => (PAGE_COLOURS.find(([p]) => path.startsWith(p)) || [null, 'cream'])[1];

function Shell() {
  const { pathname } = useLocation();
  useEffect(() => { document.documentElement.dataset.page = pageColour(pathname); }, [pathname]);
  // The landing page is a full-screen cover with its own intro
  if (pathname === '/') return <Suspense fallback={<div className="min-h-screen bg-bg-base" />}><LandingPage /></Suspense>;
  return (
    <>
      <SmoothScroll />
      <Intro />
      <CommandPalette links={NAV} />
      <div className="min-h-screen flex flex-col bg-bg-base font-main text-text-main">
        <Navbar />
        <OnboardingGate />

        <main className={pathname === '/home' ? 'flex-grow' : 'flex-grow pt-[96px]'}>
          <PageTransition>
            <Suspense fallback={<Spinner />}>
            <Routes>
              <Route path="/home" element={<HomePage />} />
              <Route path="/explore" element={<ExplorePage />} />
              <Route path="/flips" element={<FlipsPage />} />
              <Route path="/reels" element={<Navigate to="/flips" replace />} />
              <Route path="/shuffle" element={<Navigate to="/flips" replace />} />
              <Route path="/quiz" element={<QuizPage />} />
              <Route path="/messages" element={<MessagesPage />} />
              <Route path="/messages/:username" element={<MessagesPage />} />
              <Route path="/search" element={<SearchPage />} />
              <Route path="/book/:title" element={<BookDetailsPage />} />
              <Route path="/author/:name" element={<AuthorDetailsPage />} />
              <Route path="/library" element={<MyLibraryPage />} />
              <Route path="/lists" element={<ListsPage />} />
              <Route path="/lists/new" element={<NewListPage />} />
              <Route path="/lists/:id" element={<ListDetailPage />} />
              <Route path="/feed" element={<FeedPage />} />
              <Route path="/people" element={<PeoplePage />} />
              <Route path="/friends" element={<Navigate to="/people" replace />} />
              <Route path="/u/:username" element={<ProfilePage />} />
              <Route path="/u/:username/stats" element={<StatsPage />} />
              <Route path="/settings" element={<SettingsPage />} />
              <Route path="/chat" element={<ChatPage />} />
              <Route path="/admin" element={<AdminPage />} />
              <Route path="*" element={<Navigate to="/home" replace />} />
            </Routes>
            </Suspense>
          </PageTransition>
        </main>

        <Footer />
      </div>
    </>
  );
}

function App() {
  return (
    <AuthProvider>
      <Router>
        <PulseProvider>
          <Shell />
        </PulseProvider>
      </Router>
    </AuthProvider>
  );
}

export default App;
