import {
  useState,
  useId,
  isValidElement,
  cloneElement,
  type ReactElement,
  type ReactNode,
  type FormEvent,
} from "react";
import { X, LoaderCircle, Inbox, AlertCircle } from "lucide-react";
import { Button as TemplateButton } from "./ui/button";
export function Button({
  children,
  busy = false,
  kind = "",
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  busy?: boolean;
  kind?: string;
}) {
  return (
    <TemplateButton
      {...props}
      className={"button " + kind + " " + (props.className || "")}
      disabled={props.disabled || busy}
    >
      {busy && <LoaderCircle size={16} className="spin" />}
      {children}
    </TemplateButton>
  );
}
export function Notice({
  children,
  success = false,
}: {
  children: ReactNode;
  success?: boolean;
}) {
  return children ? (
    <div role="status" className={"notice " + (success ? "success" : "")}>
      <AlertCircle size={16} />
      <span>{children}</span>
    </div>
  ) : null;
}
export function Empty({
  title,
  children,
}: {
  title: string;
  children?: ReactNode;
}) {
  return (
    <div className="empty">
      <Inbox size={36} />
      <h3>{title}</h3>
      <p>{children}</p>
    </div>
  );
}
export function Modal({
  title,
  children,
  onClose,
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
}) {
  return (
    <div
      className="overlay"
      onKeyDown={(e) => {
        if (e.key === "Escape") onClose();
      }}
    >
      <section
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <header>
          <h2>{title}</h2>
          <button className="icon-button" aria-label="关闭" onClick={onClose}>
            <X size={20} />
          </button>
        </header>
        {children}
      </section>
    </div>
  );
}
export function Field({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  const id = useId();
  const control = isValidElement(children)
    ? cloneElement(children as ReactElement<any>, {
        id,
        "aria-label": (children.props as any)["aria-label"] || label,
      })
    : children;
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      {control}
    </div>
  );
}
export function useAction() {
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [success, setSuccess] = useState("");
  const run = async (fn: () => Promise<void>, message = "") => {
    setBusy(true);
    setError("");
    setSuccess("");
    try {
      await fn();
      setSuccess(message);
    } catch (e) {
      setError(e instanceof Error ? e.message : "操作失败");
    } finally {
      setBusy(false);
    }
  };
  const clearStatus = () => {
    setError("");
    setSuccess("");
  };
  return { busy, error, success, run, setError, clearStatus };
}
export function Form({
  children,
  onSubmit,
}: {
  children: ReactNode;
  onSubmit: () => void;
}) {
  return (
    <form
      onSubmit={(e: FormEvent) => {
        e.preventDefault();
        onSubmit();
      }}
    >
      {children}
    </form>
  );
}
