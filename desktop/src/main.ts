import { mount } from "svelte";
import App from "./App.svelte";
import "@qualsched/ui/app.css";

export default mount(App, { target: document.getElementById("app")! });
