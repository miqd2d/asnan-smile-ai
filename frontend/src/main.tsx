import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";
import { VoiceAssistantPage } from "./pages/VoiceAssistantPage";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <VoiceAssistantPage />
  </StrictMode>,
);
