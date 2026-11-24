import { initializeApp } from 'firebase/app';
import { getAuth, GoogleAuthProvider } from 'firebase/auth';

const firebaseConfig = {
  apiKey: "AIzaSyAiU-HVwaNoKyWMmr1gc0UHEPPKvss-zLc",
  authDomain: "booklog-9cf65.firebaseapp.com",
  projectId: "booklog-9cf65",
  storageBucket: "booklog-9cf65.firebasestorage.app",
  messagingSenderId: "327205213975",
  appId: "1:327205213975:web:2e81a96376e735cee18952"
};

const app = initializeApp(firebaseConfig);
export const auth = getAuth(app);
export const googleProvider = new GoogleAuthProvider();

export default app;
