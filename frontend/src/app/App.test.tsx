import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { App } from "./App";

describe("App", () => {
  it("renders the upload page and workflow navigation", () => {
    render(
      <MemoryRouter initialEntries={["/"]}>
        <App />
      </MemoryRouter>
    );

    expect(screen.getByRole("heading", { name: /from tender to contender/i })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /welcome - let's price your tender/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /estimate & review/i })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /processing/i })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /proceed to estimate & review/i })).toBeDisabled();
  });

  it("shows bid page needs a processed job before scenarios", () => {
    render(
      <MemoryRouter initialEntries={["/bid"]}>
        <App />
      </MemoryRouter>
    );

    expect(screen.getByRole("heading", { name: /bid optimization/i })).toBeInTheDocument();
    expect(screen.getByText(/no processed job selected/i)).toBeInTheDocument();
  });
});
