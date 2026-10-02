"use client";

import { useEffect, useRef } from "react";
import { loginWithGoogle, AuthError } from "@/lib/auth/auth-client";

// Minimal shape of the Google Identity Services API we use.
// https://developers.google.com/identity/gsi/web/reference/js-reference
interface GoogleCredentialResponse {
  credential: string;
}

interface GoogleAccountsId {
  initialize(config: {
    client_id: string;
    callback: (response: GoogleCredentialResponse) => void;
  }): void;
  renderButton(
    parent: HTMLElement,
    options: { theme?: string; size?: string; width?: number; text?: string }
  ): void;
}

declare global {
  interface Window {
    google?: { accounts: { id: GoogleAccountsId } };
  }
}

const SCRIPT_ID = "google-identity-services";

function loadGoogleScript(): Promise<void> {
  if (window.google?.accounts?.id) return Promise.resolve();
  const existing = document.getElementById(SCRIPT_ID);
  if (existing) {
    return new Promise((resolve) => existing.addEventListener("load", () => resolve()));
  }
  return new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.id = SCRIPT_ID;
    script.src = "https://accounts.google.com/gsi/client";
    script.async = true;
    script.defer = true;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("Failed to load Google Identity Services"));
    document.head.appendChild(script);
  });
}

interface GoogleSignInButtonProps {
  onSuccess: () => void;
  onError: (message: string) => void;
}

export default function GoogleSignInButton({ onSuccess, onError }: GoogleSignInButtonProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const clientId = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID;

  useEffect(() => {
    if (!clientId || !containerRef.current) return;

    let cancelled = false;

    loadGoogleScript()
      .then(() => {
        if (cancelled || !containerRef.current || !window.google) return;

        window.google.accounts.id.initialize({
          client_id: clientId,
          callback: async (response) => {
            try {
              await loginWithGoogle(response.credential);
              onSuccess();
            } catch (err) {
              onError(err instanceof AuthError ? err.message : "Google sign-in failed. Please try again.");
            }
          },
        });
        window.google.accounts.id.renderButton(containerRef.current, {
          theme: "outline",
          size: "large",
          width: 320,
          text: "continue_with",
        });
      })
      .catch(() => onError("Could not load Google sign-in. Please try again later."));

    return () => {
      cancelled = true;
    };
  }, [clientId, onSuccess, onError]);

  if (!clientId) return null;

  return <div ref={containerRef} className="flex justify-center" />;
}
