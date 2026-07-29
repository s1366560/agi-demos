export async function createVisualDiff(
  page,
  webScreenshot,
  desktopScreenshot,
) {
  const result = await page.evaluate(
    async ({ webBase64, desktopBase64 }) => {
      async function decodePng(base64) {
        const binary = atob(base64);
        const bytes = Uint8Array.from(binary, (character) =>
          character.charCodeAt(0),
        );
        return createImageBitmap(new Blob([bytes], { type: "image/png" }));
      }

      const [webImage, desktopImage] = await Promise.all([
        decodePng(webBase64),
        decodePng(desktopBase64),
      ]);
      if (
        webImage.width !== desktopImage.width ||
        webImage.height !== desktopImage.height
      ) {
        throw new Error(
          "paired screenshots must have identical pixel dimensions",
        );
      }

      const canvas = document.createElement("canvas");
      canvas.width = webImage.width;
      canvas.height = webImage.height;
      const context = canvas.getContext("2d", { willReadFrequently: true });
      if (!context) throw new Error("2D canvas context is unavailable");

      context.drawImage(webImage, 0, 0);
      const webPixels = context.getImageData(0, 0, canvas.width, canvas.height);
      context.clearRect(0, 0, canvas.width, canvas.height);
      context.drawImage(desktopImage, 0, 0);
      const desktopPixels = context.getImageData(
        0,
        0,
        canvas.width,
        canvas.height,
      );
      const diffPixels = context.createImageData(canvas.width, canvas.height);

      let differingPixels = 0;
      let maximumChannelDelta = 0;
      for (let offset = 0; offset < webPixels.data.length; offset += 4) {
        let pixelDiffers = false;
        for (let channel = 0; channel < 3; channel += 1) {
          const delta = Math.abs(
            webPixels.data[offset + channel] -
              desktopPixels.data[offset + channel],
          );
          diffPixels.data[offset + channel] = delta;
          maximumChannelDelta = Math.max(maximumChannelDelta, delta);
          if (delta > 0) pixelDiffers = true;
        }
        diffPixels.data[offset + 3] = 255;
        if (pixelDiffers) differingPixels += 1;
      }
      context.putImageData(diffPixels, 0, 0);
      webImage.close();
      desktopImage.close();
      return {
        dataUrl: canvas.toDataURL("image/png"),
        observation: {
          differing_pixels: differingPixels,
          total_pixels: canvas.width * canvas.height,
          max_channel_delta: maximumChannelDelta,
        },
      };
    },
    {
      webBase64: webScreenshot.toString("base64"),
      desktopBase64: desktopScreenshot.toString("base64"),
    },
  );

  return {
    png: Buffer.from(
      result.dataUrl.replace(/^data:image\/png;base64,/u, ""),
      "base64",
    ),
    observation: result.observation,
  };
}
