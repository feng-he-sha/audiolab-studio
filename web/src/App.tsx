import type { ReactNode } from "react";
import { AppShell } from "./components/AppShell";
import { ErrorBoundary } from "./components/common/ErrorBoundary";
import { StudioProvider } from "./state/StudioContext";
import { UIProvider } from "./state/ui";

export function App(): ReactNode {
  return (
    <ErrorBoundary>
      <UIProvider>
        <StudioProvider>
          <AppShell />
        </StudioProvider>
      </UIProvider>
    </ErrorBoundary>
  );
}
