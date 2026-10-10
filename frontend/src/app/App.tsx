import { Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "../components/AppShell";
import { BidOptimizationPage } from "../pages/BidOptimizationPage";
import { EstimateReviewPage } from "../pages/EstimateReviewPage";
import { FinalOfferPage } from "../pages/FinalOfferPage";
import { ProcessingPage } from "../pages/ProcessingPage";
import { WelcomeUploadPage } from "../pages/WelcomeUploadPage";

export function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<WelcomeUploadPage />} />
        <Route path="processing" element={<ProcessingPage />} />
        <Route path="processing/:jobId" element={<ProcessingPage />} />
        <Route path="review" element={<EstimateReviewPage />} />
        <Route path="review/:jobId" element={<EstimateReviewPage />} />
        <Route path="bid" element={<BidOptimizationPage />} />
        <Route path="bid/:jobId" element={<BidOptimizationPage />} />
        <Route path="final" element={<FinalOfferPage />} />
        <Route path="final/:jobId" element={<FinalOfferPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
