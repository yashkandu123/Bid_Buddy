import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, it, vi } from "vitest";
import { ReviewNavigationContext } from "../app/ReviewNavigationContext";
import { WorkflowFooter } from "./WorkflowFooter";

it("blocks proceeding while estimator changes are pending", () => {
  render(<MemoryRouter><ReviewNavigationContext.Provider value={{ pending: true, setPending: vi.fn() }}>
    <WorkflowFooter next={{ to: "/bid/job1", label: "Bid Optimization" }} />
  </ReviewNavigationContext.Provider></MemoryRouter>);
  expect(screen.getByRole("button", { name: /proceed to bid optimization/i })).toBeDisabled();
  expect(screen.getByText(/save your estimator changes/i)).toBeInTheDocument();
});
