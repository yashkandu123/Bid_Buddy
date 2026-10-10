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

    expect(screen.getByRole("heading", { name: /from tender to first estimate/i })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /welcome & tender upload/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /estimate & review/i })).toBeInTheDocument();
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
