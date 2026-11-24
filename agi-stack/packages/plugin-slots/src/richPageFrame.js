// A trusted, separately loaded frame contains plugin navigation under its own frame-src CSP.
// Transfer one private port; the guest never receives the application's window or credentials.
window.addEventListener("message", function initialize(event) {
  if (
    event.source !== parent ||
    event.data?.type !== "memstack.page.open" ||
    event.ports.length !== 1
  )
    return;
  window.removeEventListener("message", initialize);
  const host = event.ports[0];
  const guest = document.createElement("iframe");
  guest.setAttribute("sandbox", "allow-scripts allow-forms");
  guest.title = event.data.title;
  window.addEventListener("message", function connect(message) {
    if (
      message.source !== guest.contentWindow ||
      message.origin !== "null" ||
      message.data !== "memstack.page.guest" ||
      message.ports.length !== 1
    )
      return;
    window.removeEventListener("message", connect);
    host.postMessage("memstack.page.connect", [message.ports[0]]);
    host.close();
  });
  guest.srcdoc = event.data.document;
  document.body.append(guest);
});
