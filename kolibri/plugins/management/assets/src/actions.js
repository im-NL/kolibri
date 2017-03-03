const coreApp = require('kolibri');
const logging = require('kolibri.lib.logging');

const ClassroomResource = coreApp.resources.ClassroomResource;
const FacilityResource = coreApp.resources.FacilityResource;
const MembershipResource = coreApp.resources.MembershipResource;
const FacilityUserResource = coreApp.resources.FacilityUserResource;
const TaskResource = coreApp.resources.TaskResource;
const RoleResource = coreApp.resources.RoleResource;

const coreActions = require('kolibri.coreVue.vuex.actions');
const ConditionalPromise = require('kolibri.lib.conditionalPromise');
const constants = require('./state/constants');
const UserKinds = require('kolibri.coreVue.vuex.constants').UserKinds;

const PageNames = constants.PageNames;
const ContentWizardPages = constants.ContentWizardPages;
const samePageCheckGenerator = require('kolibri.coreVue.vuex.actions').samePageCheckGenerator;


/**
 * Vuex State Mappers
 *
 * The methods below help map data from
 * the API to state in the Vuex store
 */
function _classState(data) {
  const state = {
    id: data.id,
    name: data.name,
    parent: data.parent,
    learner_count: data.learner_count,
    coach_count: data.coach_count,
    admin_count: data.admin_count,
  };
  return state;
}

function _facilityState(data) {
  const state = {
    id: data.id,
    name: data.name,
  };
  return state;
}


function _userState(apiUserData) {
  function calcUserKind() {
    if (apiUserData.roles) {
      // array of strings, where each string represents a role object
      const roleKinds = apiUserData.roles.map((roleObj) => roleObj.kind);
      if (roleKinds.includes(UserKinds.ADMIN || UserKinds.SUPERUSER)) {
        return UserKinds.ADMIN;
      } else if (roleKinds.includes(UserKinds.COACH)) {
        return UserKinds.COACH;
      }
    }
    return UserKinds.LEARNER;
  }

  return {
    id: apiUserData.id,
    facility_id: apiUserData.facility,
    username: apiUserData.username,
    full_name: apiUserData.full_name,
    kind: calcUserKind(apiUserData.roles),
  };
}


function _taskState(data) {
  const state = {
    id: data.id,
    type: data.type,
    status: data.status,
    metadata: data.metadata,
    percentage: data.percentage,
  };
  return state;
}

/**
 * Title Helper
 */

function _managePageTitle(title) {
  return `Manage ${title}`;
}


/**
 * Actions
 *
 * These methods are used to update client-side state
 */


function displayModal(store, modalName) {
  store.dispatch('SET_MODAL', modalName);
}


// ================================
// CLASSES MANAGEMENT ACTIONS

/**
 * Do a POST to create new class
 * @param {object} stateClassData
 *  Needed: name
 */
function createClass(store, stateClassData) {
  const classData = {
    name: stateClassData.name,
    parent: stateClassData.facilityId,
  };

  ClassroomResource.createModel(classData).save().then(
    cl => {
      // dispatch newly created class
      store.dispatch('ADD_CLASS', _classState(cl));
      displayModal(store, false);
    },
    error => { coreActions.handleApiError(store, error); }
  );
}

/**
 * Do a DELETE to delete the class.
 * @param {string or Integer} id
 */
function deleteClass(store, id) {
  if (!id) {
    // if no id passed, abort the function
    return;
  }
  ClassroomResource.getModel(id).delete().then(
    cl => {
      store.dispatch('DELETE_CLASS', id);
      displayModal(store, false);
    },
    error => { coreActions.handleApiError(store, error); }
  );
}

/**
 * Do a PATCH to update the class.
 * @param {string} id - class id.
 * @param {object} updateData.
 */
function updateClass(store, id, updateData) {
  if (!id || Object.keys(updateData).length === 0) {
    // if no id or empty updateData passed, abort the function
    return;
  }
  const classModel = ClassroomResource.getModel(id);

  classModel.save(updateData).then(
    response => {
      store.dispatch('UPDATE_CLASS', id, response);
      displayModal(store, false);
    },
    error => { coreActions.handleApiError(store, error); }
  );
}

function removeClassUser(store, classId, userId) {
  if (!classId || !userId) {
    // if no id passed, abort the function
    return;
  }
  // fetch the membership model with this classId and userId.
  const MembershipCollection = MembershipResource.getCollection({
    user_id: userId,
    collection_id: classId,
  });

  MembershipCollection.fetch().then(
    (membership) => {
      const membershipId = membership[0].id; // will always only have one item in the array.
      MembershipResource.getModel(membershipId).delete().then(
        response => {
          store.dispatch('DELETE_USER', userId);
          displayModal(store, false);
        },
        error => { coreActions.handleApiError(store, error); }
      );
    }
  );
}

function showClassesPage(store) {
  store.dispatch('CORE_SET_PAGE_LOADING', true);
  store.dispatch('SET_PAGE_NAME', PageNames.CLASS_MGMT_PAGE);
  const classCollection = ClassroomResource.getCollection();
  const classPromise = classCollection.fetch({}, true);
  const facilityCollection = FacilityResource.getCollection();
  const facilityPromise = facilityCollection.fetch();

  const promises = [facilityPromise, classPromise];

  ConditionalPromise.all(promises).only(
    samePageCheckGenerator(store),
    ([facility, classes]) => {
      const pageState = {
        modalShown: null,
        facility: _facilityState(facility[0]), // for mvp, we assume only one facility exists
        classes: classes.map(_classState),
      };

      store.dispatch('SET_PAGE_STATE', pageState);
      store.dispatch('CORE_SET_PAGE_LOADING', false);
      store.dispatch('CORE_SET_ERROR', null);
      store.dispatch('CORE_SET_TITLE', _managePageTitle('Classes'));
    },
    error => { coreActions.handleApiError(store, error); }
  );
}

function showClassEditPage(store, classId) {
  store.dispatch('CORE_SET_PAGE_LOADING', true);
  store.dispatch('SET_PAGE_NAME', PageNames.CLASS_EDIT_MGMT_PAGE);

  const classModel = ClassroomResource.getModel(classId);
  const classPromise = classModel.fetch();
  // fetch the users under this class.
  const classUsersCollection = FacilityUserResource.getCollection({ member_of: classId });
  const classUsersPromise = classUsersCollection.fetch();

  const promises = [classUsersPromise, classPromise];

  ConditionalPromise.all(promises).only(
    samePageCheckGenerator(store),
    ([users, cl]) => {
      const pageState = {
        modalShown: null,
        classes: [cl],
        users: users.map(_userState),
      };
      store.dispatch('SET_PAGE_STATE', pageState);
      store.dispatch('CORE_SET_PAGE_LOADING', false);
      store.dispatch('CORE_SET_ERROR', null);
      store.dispatch('CORE_SET_TITLE', _managePageTitle('Classes'));
    },
    error => { coreActions.handleApiError(store, error); }
  );
}


function showClassEnrollPage(store, classId) {
  store.dispatch('CORE_SET_PAGE_LOADING', true);
  store.dispatch('SET_PAGE_NAME', PageNames.CLASS_ENROLL_MGMT_PAGE);
  store.dispatch('CORE_SET_TITLE', _managePageTitle('Classes'));
  store.dispatch('CORE_SET_ERROR', null);

  // current facility
  const facilityPromise = FacilityResource.getCollection().fetch();
  // all users in facility
  const userPromise = FacilityUserResource.getCollection().fetch({}, true);
  // current class
  const classPromise = ClassroomResource.getModel(classId).fetch();
  // users in current class
  const classUsersPromise = FacilityUserResource.getCollection({ member_of: classId }).fetch();

  ConditionalPromise.all([facilityPromise, userPromise, classPromise, classUsersPromise]).only(
    samePageCheckGenerator(store),
    ([facility, facilityUsers, classroom, clasroomUsers]) => {
      const pageState = {
        facility: _facilityState(facility[0]),
        facilityUsers: facilityUsers.map(_userState),
        clasroomUsers: clasroomUsers.map(_userState),
        classroom,
      };
      store.dispatch('SET_PAGE_STATE', pageState);
      store.dispatch('CORE_SET_PAGE_LOADING', false);
    },
    error => {
      coreActions.handleApiError(store, error);
    }
  );
}


function enrollUsersInClass(store, classId, users) {
  return new Promise((resolve, reject) => {
    users.forEach((userId) => {
      MembershipResource.createModel({ collection: classId, user: userId }).save().then(
        membershipModel => {
          resolve(userId);
        },
        error => {
          reject(error);
        }
      );
    });
  });
}

// ================================
// USERS MANAGEMENT ACTIONS

/**
 * Does a POST request to assign a user role (only used in this file)
 * @param {object} user
 * Needed: id, facility, kind
 */
function assignUserRole(user, kind) {
  const rolePayload = {
    user: user.id,
    collection: user.facility,
    kind,
  };

  return new Promise((resolve, reject) => {
    RoleResource.createModel(rolePayload).save().then(
      roleModel => {
        // add role to user's attribute here to limit API call
        user.roles.push(roleModel);
        resolve(user);
      },
      error => reject(error)
    );
  });
}

/**
 * Do a POST to create new user
 * @param {object} stateUserData
 *  Needed: username, full_name, facility, role, password
 */
function createUser(store, stateUserData) {
  const userData = {
    facility: store.state.pageState.facility_id,
    username: stateUserData.username,
    full_name: stateUserData.full_name,
    password: stateUserData.password,
  };

  return new Promise((resolve, reject) => {
    FacilityUserResource.createModel(userData).save().then(
      (userModel) => {
        // only runs if there's a role to be assigned
        if (stateUserData.kind !== UserKinds.LEARNER) {
          assignUserRole(userModel, stateUserData.kind).then(
            userWithRole => resolve(userWithRole),
            error => reject(error)
          );
        } else {
          // no role to assigned
          resolve(userModel);
        }
      },
      (error) => reject(error)
    );
  }).then(
    // dispatch newly created user
    newUser => store.dispatch('ADD_USER', _userState(newUser)),
    // send back error if necessary
    error => Promise.reject(error)
  );
}

/**
 * Do a PATCH to update existing user
 * @param {object} stateUser
 * Needed: id
 * Optional Changes: full_name, username, password, facility, kind(role)
 */
function updateUser(store, stateUser) {
  // payload needs username, fullname, and facility
  const userID = stateUser.id;
  const savedUserModel = FacilityUserResource.getModel(userID);
  const savedUser = savedUserModel.attributes;
  const changedValues = {};
  let roleAssigned = Promise.resolve(savedUserModel.attributes);

  // explicit checks for the only values that can be changed
  if (stateUser.full_name && stateUser.full_name !== savedUser.full_name) {
    changedValues.full_name = stateUser.full_name;
  }
  if (stateUser.username && stateUser.username !== savedUser.username) {
    changedValues.username = stateUser.username;
  }
  if (stateUser.password && stateUser.password !== savedUser.password) {
    changedValues.password = stateUser.password;
  }

  if (stateUser.kind && stateUser.kind !== _userState(savedUser).kind) {
    // assumes there's no previous roles to delete at first
    let handlePreviousRoles = Promise.resolve();

    if (savedUser.roles.length) {
      const roleDeletes = [];
      savedUser.roles.forEach(role => {
        roleDeletes.push(RoleResource.getModel(role.id).delete());
      });

      // delete the old role models if this was not a learner
      handlePreviousRoles = Promise.all(roleDeletes).then(
        responses => {
          // to avoid having to make an API call, clear manually
          savedUser.roles = [];
          return responses;
        },
        // models could not be deleted
        error => error
      );
    }

    // then assign the new role
    roleAssigned = new Promise((resolve, reject) => {
      // Take care of previous roles if necessary (will autoresolve if not)
      handlePreviousRoles.catch(error => reject(error));

      // only need to assign a new role if not a learner
      if (stateUser.kind !== UserKinds.LEARNER) {
        assignUserRole(savedUser, stateUser.kind).then(
          (updated) => resolve(updated),
          (error) => coreActions.handleApiError(store, error)
        );
      } else {
        // new role is learner - having deleted old roles is enough
        resolve(savedUser);
      }
    });
  }

  roleAssigned.then(userWithRole => {
    // update user object with new values
    savedUserModel.save(changedValues).then(userWithAttrs => {
      // dispatch changes to store
      store.dispatch('UPDATE_USERS', [_userState(userWithAttrs)]);
    });
  });
}

/**
 * Do a DELETE to delete the user.
 * @param {string or Integer} id
 */
function deleteUser(store, id) {
  if (!id) {
    // if no id passed, abort the function
    return;
  }
  FacilityUserResource.getModel(id).delete().then(
    user => { store.dispatch('DELETE_USER', id); },
    error => { coreActions.handleApiError(store, error); }
  );
}


// An action for setting up the initial state of the app by fetching data from the server
function showUserPage(store) {
  store.dispatch('CORE_SET_PAGE_LOADING', true);
  store.dispatch('SET_PAGE_NAME', PageNames.USER_MGMT_PAGE);
  const userCollection = FacilityUserResource.getCollection();
  const facilityIdPromise = FacilityUserResource.getCurrentFacility();
  const userPromise = userCollection.fetch({}, true);

  const promises = [facilityIdPromise, userPromise];

  ConditionalPromise.all(promises).only(
    samePageCheckGenerator(store),
    ([facilityId, users]) => {
      const pageState = {
        users: users.map(_userState),
        facility_id: facilityId[0],
      };
      store.dispatch('SET_PAGE_STATE', pageState);
      store.dispatch('CORE_SET_PAGE_LOADING', false);
      store.dispatch('CORE_SET_ERROR', null);
      store.dispatch('CORE_SET_TITLE', _managePageTitle('Users'));
    },
    error => { coreActions.handleApiError(store, error); }
  );
}


// ================================
// CONTENT IMPORT/EXPORT ACTIONS


function showContentPage(store) {
  store.dispatch('CORE_SET_PAGE_LOADING', true);
  store.dispatch('SET_PAGE_NAME', PageNames.CONTENT_MGMT_PAGE);
  const taskCollectionPromise = TaskResource.getCollection().fetch();
  taskCollectionPromise.only(
    samePageCheckGenerator(store),
    (taskList) => {
      const pageState = {
        taskList: taskList.map(_taskState),
        wizardState: { shown: false },
      };
      coreActions.setChannelInfo(store).then(() => {
        store.dispatch('SET_PAGE_STATE', pageState);
        store.dispatch('CORE_SET_PAGE_LOADING', false);
        store.dispatch('CORE_SET_TITLE', _managePageTitle('Content'));
      });
    },
    error => { coreActions.handleApiError(store, error); }
  );
}

function updateWizardLocalDriveList(store) {
  const localDrivesPromise = TaskResource.localDrives();
  store.dispatch('SET_CONTENT_PAGE_WIZARD_BUSY', true);
  localDrivesPromise.then((response) => {
    store.dispatch('SET_CONTENT_PAGE_WIZARD_BUSY', false);
    store.dispatch('SET_CONTENT_PAGE_WIZARD_DRIVES', response.entity);
  })
  .catch((error) => {
    store.dispatch('SET_CONTENT_PAGE_WIZARD_BUSY', false);
    coreActions.handleApiError(store, error);
  });
}

function startImportWizard(store) {
  store.dispatch('SET_CONTENT_PAGE_WIZARD_STATE', {
    shown: true,
    page: ContentWizardPages.CHOOSE_IMPORT_SOURCE,
    error: null,
    busy: false,
    drivesLoading: false,
    driveList: null,
  });
}

function startExportWizard(store) {
  store.dispatch('SET_CONTENT_PAGE_WIZARD_STATE', {
    shown: true,
    page: ContentWizardPages.EXPORT,
    error: null,
    busy: false,
    drivesLoading: false,
    driveList: null,
  });
  updateWizardLocalDriveList(store);
}

function showImportNetworkWizard(store) {
  store.dispatch('SET_CONTENT_PAGE_WIZARD_STATE', {
    shown: true,
    page: ContentWizardPages.IMPORT_NETWORK,
    error: null,
    busy: false,
    drivesLoading: false,
    driveList: null,
  });
}

function showImportLocalWizard(store) {
  store.dispatch('SET_CONTENT_PAGE_WIZARD_STATE', {
    shown: true,
    page: ContentWizardPages.IMPORT_LOCAL,
    error: null,
    busy: false,
    drivesLoading: false,
    driveList: null,
  });
  updateWizardLocalDriveList(store);
}

function cancelImportExportWizard(store) {
  store.dispatch('SET_CONTENT_PAGE_WIZARD_STATE', {
    shown: false,
    error: null,
    busy: false,
    drivesLoading: false,
    driveList: null,
  });
}

// called from a timer to continually update UI
function pollTasksAndChannels(store) {
  const samePageCheck = samePageCheckGenerator(store);
  TaskResource.getCollection().fetch({}, true).only(
    // don't handle response if we've switched pages or if we're in the middle of another operation
    () => samePageCheck() && !store.state.pageState.wizardState.busy,
    (taskList) => {
      // Perform channel poll AFTER task poll to ensure UI is always in a consistent state.
      // I.e. channel list always reflects the current state of ongoing task(s).
      coreActions.setChannelInfo(store).only(
        samePageCheckGenerator(store),
        () => {
          store.dispatch('SET_CONTENT_PAGE_TASKS', taskList.map(_taskState));
          // Close the wizard if there's an outstanding task.
          // (this can be removed when we support more than one
          // concurrent task.)
          if (taskList.length && store.state.pageState.wizardState.shown) {
            cancelImportExportWizard(store);
          }
        }
      );
    },
    error => { logging.error(`poll error: ${error}`); }
  );
}

function clearTask(store, taskId) {
  const clearTaskPromise = TaskResource.clearTask(taskId);
  clearTaskPromise.then(() => {
    store.dispatch('SET_CONTENT_PAGE_TASKS', []);
  })
  .catch(error => { coreActions.handleApiError(store, error); });
}

function triggerLocalContentImportTask(store, driveId) {
  store.dispatch('SET_CONTENT_PAGE_WIZARD_BUSY', true);
  const localImportPromise = TaskResource.localImportContent(driveId);
  localImportPromise.then((response) => {
    store.dispatch('SET_CONTENT_PAGE_TASKS', [_taskState(response.entity)]);
    cancelImportExportWizard(store);
  })
  .catch((error) => {
    store.dispatch('SET_CONTENT_PAGE_WIZARD_ERROR', error.status.text);
    store.dispatch('SET_CONTENT_PAGE_WIZARD_BUSY', false);
  });
}

function triggerLocalContentExportTask(store, driveId) {
  store.dispatch('SET_CONTENT_PAGE_WIZARD_BUSY', true);
  const localExportPromise = TaskResource.localExportContent(driveId);
  localExportPromise.then((response) => {
    store.dispatch('SET_CONTENT_PAGE_TASKS', [_taskState(response.entity)]);
    cancelImportExportWizard(store);
  })
  .catch((error) => {
    store.dispatch('SET_CONTENT_PAGE_WIZARD_ERROR', error.status.text);
    store.dispatch('SET_CONTENT_PAGE_WIZARD_BUSY', false);
  });
}

function triggerRemoteContentImportTask(store, channelId) {
  store.dispatch('SET_CONTENT_PAGE_WIZARD_BUSY', true);
  const remoteImportPromise = TaskResource.remoteImportContent(channelId);
  remoteImportPromise.then((response) => {
    store.dispatch('SET_CONTENT_PAGE_TASKS', [_taskState(response.entity)]);
    cancelImportExportWizard(store);
  })
  .catch((error) => {
    if (error.status.code === 404) {
      store.dispatch('SET_CONTENT_PAGE_WIZARD_ERROR', 'That ID was not found on our server.');
    } else {
      store.dispatch('SET_CONTENT_PAGE_WIZARD_ERROR', error.status.text);
    }
    store.dispatch('SET_CONTENT_PAGE_WIZARD_BUSY', false);
  });
}


// ================================
// OTHER ACTIONS


function showDataPage(store) {
  store.dispatch('SET_PAGE_NAME', PageNames.DATA_EXPORT_PAGE);
  store.dispatch('SET_PAGE_STATE', {});
  store.dispatch('CORE_SET_PAGE_LOADING', false);
  store.dispatch('CORE_SET_ERROR', null);
  store.dispatch('CORE_SET_TITLE', _managePageTitle('Data'));
}

function showScratchpad(store) {
  store.dispatch('SET_PAGE_NAME', PageNames.SCRATCHPAD);
  store.dispatch('SET_PAGE_STATE', {});
  store.dispatch('CORE_SET_PAGE_LOADING', false);
  store.dispatch('CORE_SET_ERROR', null);
  store.dispatch('CORE_SET_TITLE', _managePageTitle('Scratchpad'));
}

module.exports = {
  displayModal,

  createClass,
  deleteClass,
  updateClass,
  removeClassUser,
  showClassesPage,
  showClassEditPage,
  showClassEnrollPage,
  enrollUsersInClass,

  createUser,
  updateUser,
  deleteUser,
  showUserPage,

  showContentPage,
  pollTasksAndChannels,
  clearTask,
  startImportWizard,
  startExportWizard,
  showImportNetworkWizard,
  showImportLocalWizard,
  cancelImportExportWizard,
  triggerLocalContentExportTask,
  triggerLocalContentImportTask,
  triggerRemoteContentImportTask,
  updateWizardLocalDriveList,

  showDataPage,
  showScratchpad,
};
