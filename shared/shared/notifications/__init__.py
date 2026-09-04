"""Channel-neutral notifications (architecture, notification channels). Email and Telegram are
the first channels; `render` builds the message, the channel modules deliver it. Used by the
automation service for actions and by the API for test messages and auth mail."""
