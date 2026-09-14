Feature: The microphone stays open for follow-ups
  As someone controlling my Linux desktop by voice
  I want EasySpeak to keep listening after it acted, replied or missed
  So that I can go on, or try again, without repeating the wake word

  (**Note:** These drive the real run() loop with a stubbed microphone: the
  wake word fires once, the scripted utterances follow, and the run ends when
  EasySpeak goes back to listening for the wake word. A session that ended
  early leaves utterances unheard; one that never ends runs out of script.)

  Background:
    Given a fresh EasySpeak that understands only "help" and "open files"

  Scenario: A spoken reply does not close the session
    When the wake word fires and I say "open files", "open files", then fall silent
    Then both commands are carried out on the one wake word
    And each reply is drained before the next listen

  Scenario: A miss does not close the session
    When the wake word fires and I say "flibbertigibbet", "open files", then fall silent
    Then "open files" is carried out on the one wake word
    And the apology is drained before the next listen

  Scenario: Two quiet listens end the session
    When the wake word fires and I say "open files", then fall silent
    Then EasySpeak listens twice more, then waits for the wake word again

  # Regression: the follow-up window used to stay open on "stop listening" too,
  # so EasySpeak confirmed voice control was off and then carried on hearing,
  # and acting on, whatever was said next.
  Scenario: "Stop listening" closes the session and releases the mic at once
    Given the sleep plugin is loaded as well
    When the wake word fires and I say "stop listening", then EasySpeak is reactivated from the tray
    Then the mic is released before EasySpeak listens again
    And the confirmation is drained before the mic is released
