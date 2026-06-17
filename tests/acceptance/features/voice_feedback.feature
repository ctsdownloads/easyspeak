Feature: Spoken voice feedback
  As someone controlling my Linux desktop by voice
  I want each command confirmed by immediate spoken feedback
  So that I know it registered without watching the screen

  (**Note:** The real piper/player binaries are exercised
  separately in tests/integration.)

  Scenario: The voice model is loaded only once across phrases
    Given a fresh EasySpeak with a stubbed speech pipeline
    When I speak "opening files"
    And I speak "closing files"
    Then the voice model is loaded only once
    And both phrases are sent to the speech pipeline

  Scenario: Blank feedback is never spoken
    Given a fresh EasySpeak with a stubbed speech pipeline
    When I speak "   "
    Then no speech pipeline is started

  Scenario: A final phrase is heard in full on shutdown
    Given a fresh EasySpeak with a stubbed speech pipeline
    And I have spoken "goodbye"
    When the app drains speech on shutdown
    Then the pending phrase is flushed and played to completion

  Scenario: Speech recovers when the pipeline breaks
    Given a fresh EasySpeak whose speech pipeline fails once then recovers
    When I speak "open browser"
    Then the phrase is delivered after the pipeline is rebuilt
