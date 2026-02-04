import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Select } from "../Select";

const options = [
  { value: "option1", label: "Option 1" },
  { value: "option2", label: "Option 2" },
  { value: "option3", label: "Option 3" },
];

describe("Select", () => {
  it("should render without label", () => {
    render(<Select options={options} />);

    const select = screen.getByRole("combobox");
    expect(select).toBeInTheDocument();
  });

  it("should render with label", () => {
    render(<Select label="Choose option" options={options} />);

    const select = screen.getByRole("combobox");
    const label = screen.getByText("Choose option");

    expect(select).toBeInTheDocument();
    expect(label).toBeInTheDocument();
  });

  it("should render all options", () => {
    render(<Select options={options} />);

    expect(screen.getByRole("option", { name: "Option 1" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Option 2" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Option 3" })).toBeInTheDocument();
  });

  it("should generate ID from label", () => {
    render(<Select label="Select Type" options={options} />);

    const select = screen.getByRole("combobox");
    expect(select).toHaveAttribute("id", "select-type");
  });

  it("should use custom ID when provided", () => {
    render(<Select label="Test" id="custom-id" options={options} />);

    const select = screen.getByRole("combobox");
    expect(select).toHaveAttribute("id", "custom-id");
  });

  it("should display error message", () => {
    render(<Select options={options} error="This field is required" />);

    const error = screen.getByText("This field is required");
    expect(error).toBeInTheDocument();
    expect(error).toHaveClass("text-neon-red");
  });

  it("should apply error styles when error is provided", () => {
    render(<Select options={options} error="Error message" />);

    const select = screen.getByRole("combobox");
    expect(select).toHaveClass("border-neon-red");
  });

  it("should call onChange when value changes", async () => {
    let selectedValue = "";
    const handleChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
      selectedValue = e.target.value;
    };

    render(<Select options={options} onChange={handleChange} />);

    const select = screen.getByRole("combobox");
    await userEvent.selectOptions(select, "option2");

    expect(selectedValue).toBe("option2");
  });

  it("should apply custom className", () => {
    render(<Select options={options} className="custom-class" />);

    const select = screen.getByRole("combobox");
    expect(select).toHaveClass("custom-class");
  });

  it("should support disabled state", () => {
    render(<Select options={options} disabled />);

    const select = screen.getByRole("combobox");
    expect(select).toBeDisabled();
  });

  it("should respect value prop", () => {
    render(<Select options={options} value="option2" onChange={() => {}} />);

    const select = screen.getByRole("combobox") as HTMLSelectElement;
    expect(select.value).toBe("option2");
  });
});
