import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import * as Sentry from "@sentry/react";
import App from "./App";
import { initSentry } from "./lib/sentry";
import '@fontsource-variable/space-grotesk';
import '@fontsource-variable/manrope';
import "./index.css";

// Only replace React's default console reporting when there is somewhere to send errors.
const rootOptions = initSentry()
  ? {
      onUncaughtError: Sentry.reactErrorHandler(),
      onCaughtError: Sentry.reactErrorHandler(),
      onRecoverableError: Sentry.reactErrorHandler(),
    }
  : {};

ReactDOM.createRoot(document.getElementById("root"), rootOptions).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>
);
