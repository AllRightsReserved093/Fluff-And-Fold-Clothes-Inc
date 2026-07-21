# The Laundry

## Background

You are an engineer at **Fluff & Fold Clothes Inc.**, tasked with building a service that designs equipment maintenance tracking solutions for laundromats. The purpose of the system is to track and administer the status of each washer and dryer in the laundry.

You may assume that each washer/dryer unit can communicate to a server/office PC that lives on the same premises via a REST API, and that this client ability is preconfigured on the washers/dryers to post to a specific IP address or hostname. The customer is the **attendant** in the laundry, who will be using an interface hosted on that machine.

## Architecture Overview

Machines post sensor readings to the office PC:

```
POST laundry_host/api/readings
Body: { ... }
```

The attendant uses that office PC to monitor the state of the machines. You can install various packages, servers, or services on the device.

> **Suggested starting point:** a system diagram and a data model of the items that live inside the laundry.

## Operating Assumptions

- Customers want to use an interface to view the current state of the machines
- Each location will have multiple washers and dryers (e.g. 20 washers, 16 dryers)
- Anomalous temperature or other readings should be surfaced to the operator

## Your Task

1. **Server** — Write a basic server implementation that accepts sensor readings, as if running on the office PC
2. **Clients** — Write example clients that emulate washers or dryers posting data to that API
3. **Queries** — Show examples of how to query sensor readings based on criteria you define. How can the attendant identify problems with machines or confirm nominal operation?

> You do not need to build a UI.

## Deliverable

Be prepared to screenshare and explain your implementation and why you built it the way you did.