import { createContext, useContext } from "react";

export const ReviewNavigationContext = createContext({ pending: false, setPending: (_value: boolean) => {} });
export const useReviewNavigation = () => useContext(ReviewNavigationContext);
