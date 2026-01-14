import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { Badge } from "../Badge";

describe("Badge", () => {
  it("should render with default muted variant", () => {
    render(<Badge>Test Badge</Badge>);

    const badge = screen.getByText("Test Badge");
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveClass("bg-gray-300", "text-gray-700");
  });

  it("should render with success variant", () => {
    render(<Badge variant="success">Success</Badge>);

    const badge = screen.getByText("Success");
    expect(badge).toHaveClass("bg-neon-green", "text-gray-900");
  });

  it("should render with danger variant", () => {
    render(<Badge variant="danger">Danger</Badge>);

    const badge = screen.getByText("Danger");
    expect(badge).toHaveClass("bg-neon-red", "text-white");
  });

  it("should render with warning variant", () => {
    render(<Badge variant="warning">Warning</Badge>);

    const badge = screen.getByText("Warning");
    expect(badge).toHaveClass("bg-yellow-500", "text-gray-900");
  });

  it("should render with info variant", () => {
    render(<Badge variant="info">Info</Badge>);

    const badge = screen.getByText("Info");
    expect(badge).toHaveClass("bg-electric-blue", "text-white");
  });

  it("should apply custom className", () => {
    render(<Badge className="custom-class">Custom</Badge>);

    const badge = screen.getByText("Custom");
    expect(badge).toHaveClass("custom-class");
  });

  it("should render children correctly", () => {
    render(
      <Badge>
        <span>Child 1</span>
        <span>Child 2</span>
      </Badge>
    );

    expect(screen.getByText("Child 1")).toBeInTheDocument();
    expect(screen.getByText("Child 2")).toBeInTheDocument();
  });
});
