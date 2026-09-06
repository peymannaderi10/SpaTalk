import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { type Draft } from "./schemaFields";
import { ServicesTab } from "./ServicesTab";

/**
 * The Services page and a service's id.
 *
 * `services[].id` is the runtime's closed key — the tool enums, `items.service_id`,
 * the booking links — so it must exist and must never change once a service
 * has one. The clinic never sees it: a new row takes its id from the name as
 * the name is typed, made unique among the tenant's ids, and the id freezes
 * once the person moves on from the name or the config is saved.
 */

/** A trimmed copy of what `GET /internal/schema/tenant-config` serves. */
const schema = {
  $defs: {
    Service: {
      properties: {
        id: { title: "Id", type: "string" },
        name: { title: "Name", type: "string" },
        category: { title: "Category", type: "string" },
        price_text: { default: "", title: "Price Text", type: "string" },
        duration_minutes: {
          anyOf: [{ type: "integer" }, { type: "null" }],
          default: null,
          title: "Duration Minutes",
        },
        booking_url: { title: "Booking Url", type: "string" },
        consult_required: {
          default: false,
          title: "Consult Required",
          type: "boolean",
        },
        clinical: { default: false, title: "Clinical", type: "boolean" },
        description: { default: "", title: "Description", type: "string" },
      },
      required: ["id", "name", "category", "booking_url"],
      title: "Service",
      type: "object",
    },
  },
  properties: {
    services: {
      items: { $ref: "#/$defs/Service" },
      title: "Services",
      type: "array",
    },
  },
  title: "TenantConfig",
  type: "object",
};

const goldFacial = {
  id: "gold_facial",
  name: "Gold Facial",
  category: "facials",
  price_text: "from $199",
  duration_minutes: 60,
  booking_url: "https://book.example/gold",
  consult_required: false,
  clinical: false,
  description: "",
};

/**
 * The tab is controlled, so typing into a new row needs the draft to come
 * back down as a prop, as `SettingsPage` does. The spy sees every change and
 * the last one is what the runtime would be sent.
 */
function Harness({
  initial,
  spy,
}: {
  initial: Draft;
  spy: (next: Draft) => void;
}) {
  const [config, setConfig] = useState(initial);
  return (
    <ServicesTab
      config={config}
      schema={schema}
      onChange={(next) => {
        spy(next);
        setConfig(next);
      }}
      disabled={false}
    />
  );
}

function mount(initial: Draft = { services: [goldFacial] }) {
  const spy = vi.fn();
  render(<Harness initial={initial} spy={spy} />);
  return () => spy.mock.lastCall?.[0] as Draft;
}

function addService(name: string) {
  fireEvent.click(screen.getByTestId("add-service"));
  const index = screen.getAllByTestId(/^service-\d+$/).length - 1;
  fireEvent.change(screen.getByTestId(`service-${index}-name`), {
    target: { value: name },
  });
  return index;
}

describe("the Services tab", () => {
  it("renders the catalog's fields, but never the id", () => {
    mount();
    expect(screen.getByTestId("service-0-name")).toHaveValue("Gold Facial");
    expect(screen.getByTestId("service-0-category")).toBeInTheDocument();
    expect(screen.getByTestId("service-0-booking_url")).toBeInTheDocument();
    expect(screen.queryByTestId("service-0-id")).toBeNull();
    expect(screen.queryByText("Id")).toBeNull();
    expect(screen.queryByDisplayValue("gold_facial")).toBeNull();
  });

  it("gives a new service its id from the name as it is typed", () => {
    const last = mount({ services: [] });
    const index = addService("Gold Facial");
    expect(last().services[index]).toMatchObject({
      id: "gold_facial",
      name: "Gold Facial",
    });
  });

  it("makes a second Gold Facial gold_facial_2", () => {
    const last = mount();
    const index = addService("Gold Facial");
    expect(last().services[index].id).toBe("gold_facial_2");
    expect(last().services[0].id).toBe("gold_facial");
  });

  it("keeps a saved service's id when it is renamed", () => {
    const last = mount();
    fireEvent.change(screen.getByTestId("service-0-name"), {
      target: { value: "Platinum Facial" },
    });
    expect(last().services[0]).toMatchObject({
      id: "gold_facial",
      name: "Platinum Facial",
    });
  });

  it("freezes a new row's id once the person moves on from the name", () => {
    const last = mount({ services: [] });
    const index = addService("Gold");
    expect(last().services[index].id).toBe("gold");
    fireEvent.blur(screen.getByTestId(`service-${index}-name`));
    fireEvent.change(screen.getByTestId(`service-${index}-name`), {
      target: { value: "Gold Facial" },
    });
    expect(last().services[index]).toMatchObject({
      id: "gold",
      name: "Gold Facial",
    });
  });

  it("keeps the id to letters, digits and underscores, at most forty long", () => {
    const last = mount({ services: [] });
    const index = addService(
      "  Ultra-Deluxe!! 24k Gold Facial with Everything Included, Forever ",
    );
    const id = last().services[index].id;
    expect(id).toMatch(/^[a-z0-9]+(_[a-z0-9]+)*$/);
    expect(id.length).toBeLessThanOrEqual(40);
    expect(id.startsWith("ultra_deluxe_24k_gold_facial")).toBe(true);
  });

  it("removes a row, and the ids of the rows after it stay theirs", () => {
    const last = mount({
      services: [goldFacial, { ...goldFacial, id: "peel", name: "Peel" }],
    });
    const index = addService("Laser");
    expect(last().services[index].id).toBe("laser");
    fireEvent.click(
      screen.getAllByRole("button", { name: /Remove this service/ })[0],
    );
    expect(last().services.map((service: Draft) => service.id)).toEqual([
      "peel",
      "laser",
    ]);
    // The new row is still new: its id still follows its name.
    fireEvent.change(screen.getByTestId("service-1-name"), {
      target: { value: "Laser Hair" },
    });
    expect(last().services[1].id).toBe("laser_hair");
  });
});
