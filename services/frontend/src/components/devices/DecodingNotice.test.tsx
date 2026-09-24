import { render, screen } from "@testing-library/react";

import { DecodingNotice } from "@/components/devices/DecodingNotice";
import type { DeviceLogFile } from "@/api/types";
import type { Decoding } from "@/hooks/useDecoding";

const file: Decoding = {
  kind: "file",
  deviceId: "d1",
  deviceName: "SP050969",
  file: {
    id: "f1",
    device_id: "d1",
    original_filename: "log.txt",
    status: "processing",
    frames_total: 200,
    frames_done: 50,
  } as DeviceLogFile,
};

const walk: Decoding = {
  kind: "walk",
  deviceId: "d2",
  deviceName: "SP052271",
  walk: {
    identity_id: "i1",
    external_id: "0016C001F09C74FD",
    device_id: "d2",
    device_name: "SP052271",
    total: 73,
    done: 18,
  },
};

describe("DecodingNotice", () => {
  it("renders nothing when the decoder has nothing of the device", () => {
    const { container } = render(<DecodingNotice decoding={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows a file and a walk over retained uplinks, each with its bar", () => {
    render(<DecodingNotice decoding={[file, walk]} />);
    expect(
      screen.getByText("Decoding SP050969, log.txt: 50 of 200 frames, 25%."),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "Decoding the retained uplinks of SP052271: 18 of 73, 24%.",
      ),
    ).toBeInTheDocument();
    expect(screen.getAllByRole("progressbar")).toHaveLength(2);
  });
});
